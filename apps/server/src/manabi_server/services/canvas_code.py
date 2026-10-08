"""Import a course's demo code from Canvas — READ ONLY on the Canvas side.

Professors post code as Canvas pages that link to files ("Demo Code for
Polymorphism" → polymorphism.zip), or attach .c files to a module directly.
Those files are hidden from the course's Files list and are not PDF/PPTX, so
the normal importer never saw them. Each demo page (or loose code file)
becomes one code material (processing.code_bundle) in the matching module.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

import httpx
from fastapi import HTTPException
from manabi_core.models import Course, Module, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.api import canvas
from manabi_server.processing import code_bundle

log = logging.getLogger("manabi_server")

_FILE_LINK = re.compile(r"/files/(\d+)")
_MODULE_PREFIX = re.compile(r"^\s*module\s*\d+\s*[-:–]?\s*", re.I)


@dataclass
class Demo:
    canvas_module: str
    title: str
    source_url: str
    files: list[tuple[str, str]] = field(default_factory=list)
    module_id: int | None = None


def _norm(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _MODULE_PREFIX.sub("", title.lower())).strip()


def match_module(canvas_name: str, canvas_id: int, modules: list[Module]) -> Module | None:
    """The Manabi module for a Canvas module: by link, then by name ("Module
    1 - Programming Paragidms" is still "Programming Paradigms")."""
    for m in modules:
        if m.canvas_module_id == canvas_id:
            return m
    want = _norm(canvas_name)
    best, score = None, 0.0
    for m in modules:
        if m.is_general:
            continue
        s = SequenceMatcher(None, want, _norm(m.title)).ratio()
        if s > score:
            best, score = m, s
    return best if score >= 0.8 else None


async def _file_sources(
    dl: httpx.AsyncClient, token: str, file_id: int
) -> tuple[str, list[tuple[str, str]]]:
    """(display name, source files) for one Canvas file: a zip's sources,
    one code file, or nothing (PDFs, slides, binaries)."""
    meta = await canvas._canvas_get(f"/files/{file_id}")
    name = meta.get("display_name") or meta.get("filename") or str(file_id)
    is_zip = name.lower().endswith(".zip")
    if not (is_zip or code_bundle.wanted(name)) or not meta.get("url"):
        return name, []
    if int(meta.get("size") or 0) > 5_000_000:
        return name, []
    r = await dl.get(meta["url"], headers={"Authorization": f"Bearer {token}"})
    if r.status_code >= 400:
        return name, []
    if is_zip:
        # One zip is one project: its files are named under the zip so two
        # projects on a page (intvec1/intvector.h, intvec2/intvector.h) stay apart.
        stem = name[:-4]
        try:
            files = code_bundle.files_from_zip(r.content)
            return name, [(f"{stem}/{n}", t) for n, t in code_bundle.order_files(files)]
        except Exception:  # noqa: BLE001 — a bad archive skips one demo, not all
            log.warning("canvas code: unreadable zip %s", name)
            return name, []
    text = code_bundle.decode(r.content)
    return name, [(name, text)] if text is not None else []


async def collect_demos(course: Course, modules: list[Module]) -> list[Demo]:
    """Every demo page / loose code file in the course's Canvas modules."""
    cc = course.canvas_course_id
    canvas_mods = await canvas._safe_get_all(
        f"/courses/{cc}/modules", {"include[]": "items", "per_page": 100}
    )
    _, token = canvas._canvas_config()
    demos: list[Demo] = []
    async with httpx.AsyncClient(
        timeout=60, follow_redirects=True, event_hooks={"request": [canvas._read_only]}
    ) as dl:
        for cm in canvas_mods:
            target = match_module(cm.get("name") or "", int(cm.get("id") or 0), modules)
            in_pages: set[int] = set()
            loose: list[tuple[int, str]] = []
            for it in cm.get("items") or []:
                kind = it.get("type")
                if kind == "Page" and it.get("page_url"):
                    page = await canvas._canvas_get(f"/courses/{cc}/pages/{it['page_url']}")
                    ids = list(
                        dict.fromkeys(int(i) for i in _FILE_LINK.findall(page.get("body") or ""))
                    )
                    demo = Demo(
                        canvas_module=cm.get("name") or "",
                        title=it.get("title") or "Demo code",
                        source_url=f"canvas:page:{cc}:{it['page_url']}",
                        module_id=target.id if target else None,
                    )
                    for fid in ids:
                        _name, sources = await _file_sources(dl, token, fid)
                        if sources:
                            in_pages.add(fid)
                            demo.files.extend(sources)
                    if demo.files:
                        demos.append(demo)
                elif kind == "File" and code_bundle.wanted(it.get("title") or ""):
                    loose.append((int(it["content_id"]), it.get("title") or ""))
            for fid, title in loose:
                if fid in in_pages:
                    continue  # already inside a demo page's bundle
                _name, sources = await _file_sources(dl, token, fid)
                if sources:
                    demos.append(
                        Demo(
                            canvas_module=cm.get("name") or "",
                            title=title,
                            source_url=f"canvas:file:{fid}",
                            files=sources,
                            module_id=target.id if target else None,
                        )
                    )
    return demos


async def import_code_demos(
    db: AsyncSession,
    user: User,
    course: Course,
    *,
    dry_run: bool = False,
    module_map: dict[str, int] | None = None,
) -> list[dict]:
    """Collect the demos and ingest each as a code material. `module_map`
    overrides the Canvas-module → Manabi-module match by Canvas module name.
    Demos with no matching module are reported and skipped."""
    from manabi_server.api.documents import ingest_bytes  # avoid import cycle

    if not course.canvas_course_id:
        raise HTTPException(status_code=409, detail="This course is not linked to Canvas")
    modules = list(
        (await db.execute(select(Module).where(Module.course_id == course.id))).scalars().all()
    )
    by_id = {m.id: m for m in modules}
    demos = await collect_demos(course, modules)
    report = []
    for d in demos:
        if module_map and d.canvas_module in module_map:
            d.module_id = int(module_map[d.canvas_module])
        row = {
            "title": d.title,
            "canvas_module": d.canvas_module,
            "module_id": d.module_id,
            "files": [n for n, _ in d.files],
            "status": "planned" if dry_run else None,
        }
        report.append(row)
        if dry_run:
            continue
        module = by_id.get(d.module_id) if d.module_id else None
        if module is None:
            row["status"] = "skipped: no matching module"
            continue
        content = code_bundle.make_bundle(d.files).encode("utf-8")
        name = re.sub(r"[^\w .()-]+", "_", d.title).strip()[:150] or "Demo code"
        try:
            doc, job = await ingest_bytes(
                db,
                user,
                module,
                filename=f"{name}{code_bundle.BUNDLE_SUFFIX}",
                ext="txt",
                content=content,
                source_url=d.source_url,
            )
            await db.flush()
            row.update(status="imported", document_id=doc.id, job_id=job.id)
        except HTTPException as exc:
            row["status"] = "already imported" if exc.status_code == 409 else f"error: {exc.detail}"
    if not dry_run:
        await db.commit()
    return report
