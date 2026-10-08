"""Canvas LMS importer — the server proxies the Canvas REST API (the access
token never reaches the browser) and imported files enter the exact same
validation + ingestion path as manual uploads."""

import asyncio
from collections.abc import Awaitable, Iterable

import httpx
from fastapi import APIRouter, Depends, HTTPException
from manabi_core.models import Course, Module, User
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.api.documents import _doc_out, ingest_bytes
from manabi_server.api.modules import get_owned_module
from manabi_server.config import get_settings
from manabi_server.db import get_db
from manabi_server.security import get_default_user, require_csrf
from manabi_server.services.canvas_ingest import import_html_as_document

router = APIRouter(prefix="/api/canvas", tags=["canvas"])


class CanvasCourse(BaseModel):
    id: int
    name: str
    course_code: str | None


class CanvasFile(BaseModel):
    id: int
    filename: str
    size: int
    updated_at: str | None
    content_type: str | None


class ImportIn(BaseModel):
    file_id: int
    ai_included: bool = True
    # False → store + render pages only; no text extraction, chunking, or AI
    extract_text: bool = True


def _canvas_config() -> tuple[str, str]:
    settings = get_settings()
    if not settings.canvas_base_url or not settings.canvas_access_token:
        raise HTTPException(
            status_code=409,
            detail="Canvas is not configured — set CANVAS_BASE_URL and "
            "CANVAS_ACCESS_TOKEN in .env",
        )
    return settings.canvas_base_url.rstrip("/"), settings.canvas_access_token


class CanvasAuthError(HTTPException):
    """Canvas rejected the token. Distinct from a per-tab 403 so _safe_get_all
    can swallow the latter and never the former."""

    def __init__(self) -> None:
        super().__init__(
            status_code=502, detail="Canvas rejected the token — it may have expired"
        )


class CanvasRateLimited(HTTPException):
    """Canvas throttled us (403 "Rate Limit Exceeded") and kept doing so after
    the backoff. Never swallowed as "this tab is empty"."""

    def __init__(self) -> None:
        super().__init__(
            status_code=503, detail="Canvas is rate-limiting requests — try again shortly"
        )


# One keep-alive client per event loop: every Canvas call used to pay DNS +
# TCP + TLS again (~0.35 s). pytest-asyncio runs a fresh loop per test, so the
# client is rebuilt whenever the running loop (or the config) changes.
_client: httpx.AsyncClient | None = None
_client_key: tuple | None = None

_RATE_LIMIT_BACKOFF = (1.0, 2.0, 4.0)  # seconds between retries


class CanvasWriteRefused(RuntimeError):
    """Manabi only ever reads from Canvas."""


async def _read_only(request: httpx.Request) -> None:
    # The owner's rule: Canvas is read-only. Enforced on the client itself so
    # no future code path can submit, post or edit anything there.
    if request.method not in ("GET", "HEAD"):
        raise CanvasWriteRefused(f"refusing {request.method} to Canvas: read-only")


def _get_client() -> httpx.AsyncClient:
    global _client, _client_key
    base, token = _canvas_config()
    key = (id(asyncio.get_running_loop()), base, token)
    if _client is None or _client.is_closed or _client_key != key:
        _client = httpx.AsyncClient(
            base_url=f"{base}/api/v1",
            event_hooks={"request": [_read_only]},
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(20, connect=5),
            limits=httpx.Limits(
                max_connections=8, max_keepalive_connections=8, keepalive_expiry=60
            ),
        )
        _client_key = key
    return _client


async def aclose_canvas_client() -> None:
    """Close the shared client (app shutdown)."""
    global _client, _client_key
    client, _client, _client_key = _client, None, None
    if client is not None and not client.is_closed:
        await client.aclose()


def _is_rate_limited(r: httpx.Response) -> bool:
    if r.status_code == 429:
        return True
    return r.status_code == 403 and "rate limit exceeded" in r.text.lower()


async def _request(url: str, params: dict | None) -> httpx.Response:
    """GET through the shared client; retries a rate-limited response after
    1 s, 2 s and 4 s, then raises CanvasRateLimited. Auth/other errors raise."""
    client = _get_client()
    for delay in (*_RATE_LIMIT_BACKOFF, None):
        r = await client.get(url, params=params)
        if not _is_rate_limited(r):
            break
        if delay is None:
            raise CanvasRateLimited()
        await asyncio.sleep(delay)
    if r.status_code == 401:
        raise CanvasAuthError()
    if r.status_code >= 400:
        raise HTTPException(
            status_code=502, detail=f"Canvas error {r.status_code}: {r.text[:150]}"
        )
    return r




async def gather_limited[T](coros: Iterable[Awaitable[T]], n: int = 6) -> list[T]:
    """asyncio.gather with at most `n` in flight. On the first failure the
    rest are cancelled and the original exception propagates."""
    sem = asyncio.Semaphore(n)

    async def run(c: Awaitable[T]) -> T:
        async with sem:
            return await c

    tasks = [asyncio.ensure_future(run(c)) for c in coros]
    try:
        return list(await asyncio.gather(*tasks))
    except BaseException:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


async def _canvas_get(path: str, params: dict | None = None) -> list | dict:
    r = await _request(path, {"per_page": 100, **(params or {})})
    return r.json()


@router.get("/courses")
async def canvas_courses() -> list[CanvasCourse]:
    data = await _canvas_get_all(
        "/courses", {"enrollment_state": "active", "state[]": "available"}
    )
    return [
        CanvasCourse(
            id=c["id"], name=c.get("name") or "Untitled", course_code=c.get("course_code")
        )
        for c in data
        if isinstance(c, dict) and "id" in c and c.get("name")
    ]


class AnnouncementOut(BaseModel):
    id: int
    title: str
    preview: str  # single-line excerpt
    message: str  # full plain text, line breaks preserved
    posted_at: str | None
    author: str | None
    course_id: int | None
    course_code: str | None
    accent_color: str | None
    html_url: str | None


def _html_to_text(html_text: str) -> str:
    """Canvas announcement HTML → plain text with paragraph/line breaks kept."""
    import html as html_mod
    import re

    text = re.sub(r"(?i)<br\s*/?>", "\n", html_text or "")
    text = re.sub(r"(?i)</(p|div|li|h[1-6]|tr)>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "• ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html_mod.unescape(text)
    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


async def fetch_announcements(
    db: AsyncSession, user_id: int, course_id: int | None = None, limit: int = 5
) -> list[AnnouncementOut]:
    """Shared fetch core — used by the API route and the scheduler poll."""
    query = select(Course).where(
        Course.user_id == user_id,
        Course.archived_at.is_(None),
        Course.canvas_course_id.is_not(None),
    )
    if course_id is not None:
        query = query.where(Course.id == course_id)
    courses = (await db.execute(query)).scalars().all()
    if not courses:
        return []
    by_context = {f"course_{c.canvas_course_id}": c for c in courses}

    data = await _canvas_get_all(
        "/announcements",
        {
            "context_codes[]": list(by_context.keys()),
            "active_only": "true",
        },
    )
    out: list[AnnouncementOut] = []
    for a in data:
        if not isinstance(a, dict) or not a.get("id"):
            continue
        course = by_context.get(a.get("context_code", ""))
        message = _html_to_text(a.get("message", ""))
        out.append(
            AnnouncementOut(
                id=a["id"],
                title=a.get("title") or "(untitled)",
                preview=" ".join(message.split())[:280],
                message=message[:4000],
                posted_at=a.get("posted_at"),
                author=(a.get("author") or {}).get("display_name"),
                course_id=course.id if course else None,
                course_code=course.code if course else None,
                accent_color=course.accent_color if course else None,
                html_url=a.get("html_url"),
            )
        )
    out.sort(key=lambda x: x.posted_at or "", reverse=True)
    return out[: max(1, min(limit, 20))]


@router.get("/announcements")
async def canvas_announcements(
    course_id: int | None = None,
    limit: int = 5,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> list[AnnouncementOut]:
    """Latest announcements across all Canvas-linked courses (or one)."""
    return await fetch_announcements(db, user.id, course_id, limit)


IMPORTABLE_TYPES = (
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
)


@router.get("/courses/{canvas_course_id}/files")
async def canvas_files(canvas_course_id: int) -> list[CanvasFile]:
    data = await _canvas_get_all(
        f"/courses/{canvas_course_id}/files",
        {"sort": "updated_at", "order": "desc"},
    )
    out = []
    for f in data:
        if not isinstance(f, dict):
            continue
        name = (f.get("display_name") or f.get("filename") or "").lower()
        if f.get("content-type") in IMPORTABLE_TYPES or name.endswith((".pdf", ".pptx")):
            out.append(
                CanvasFile(
                    id=f["id"],
                    filename=f.get("display_name") or f.get("filename") or f"file-{f['id']}",
                    size=f.get("size") or 0,
                    updated_at=f.get("updated_at"),
                    content_type=f.get("content-type"),
                )
            )
    return out


async def _download_canvas_file(file_id: int) -> tuple[str, str, bytes]:
    """Fetch a Canvas file's metadata + bytes via its authenticated URL.
    Returns (filename, ext, content). Raises 502 / 422."""
    meta = await _canvas_get(f"/files/{file_id}")
    if not isinstance(meta, dict) or "url" not in meta:
        raise HTTPException(status_code=502, detail="Canvas file metadata unavailable")
    filename = meta.get("display_name") or meta.get("filename") or f"canvas-{file_id}"
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext not in ("pdf", "pptx"):
        raise HTTPException(status_code=422, detail="Only PDF and PPTX can be imported")
    _, token = _canvas_config()
    async with httpx.AsyncClient(
        timeout=120, follow_redirects=True, event_hooks={"request": [_read_only]}
    ) as client:
        r = await client.get(meta["url"], headers={"Authorization": f"Bearer {token}"})
    if r.status_code >= 400:
        raise HTTPException(
            status_code=502, detail=f"Canvas download failed ({r.status_code})"
        )
    return filename, ext, r.content


@router.post(
    "/modules/{module_id}/import", dependencies=[Depends(require_csrf)]
)
async def canvas_import(
    data: ImportIn,
    module: Module = Depends(get_owned_module),
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
):
    filename, ext, content = await _download_canvas_file(data.file_id)
    doc, job = await ingest_bytes(
        db,
        user,
        module,
        filename=filename,
        ext=ext,
        content=content,
        ai_included=data.ai_included and data.extract_text,
        processing_mode="full" if data.extract_text else "render_only",
        source_url=f"canvas:file:{data.file_id}",
    )
    await db.commit()
    return _doc_out(doc, job.id)


# ── Deeper sync: modules ("topics"), pages, discussions, links, syllabus ──


async def _canvas_get_all(path: str, params: dict | None = None) -> list:
    """Follow Canvas pagination (Link: rel=next) and concatenate every page."""
    results: list = []
    url: str = path
    p: dict | None = {"per_page": 100, **(params or {})}
    for _ in range(50):  # hard cap — never loop forever
        r = await _request(url, p)
        body = r.json()
        if not isinstance(body, list):
            return [body]
        results.extend(body)
        nxt = r.links.get("next", {}).get("url")
        if not nxt:
            break
        url, p = nxt, None  # the next URL already carries its params
    return results


async def canvas_assignments(canvas_course_id: int) -> list[dict]:
    """Canvas assignments with the student's own submission attached (no
    bucket — every assignment, submitted or not).

    `include[]=submission` carries score/points_possible and the submission
    state; paginated so courses with more than 100 assignments are not
    silently truncated. Shared by grades and the task sync."""
    rows = await _canvas_get_all(
        f"/courses/{canvas_course_id}/assignments", {"include[]": "submission"}
    )
    return [r for r in rows if isinstance(r, dict) and "id" in r]


async def _owned_course(course_id: int, user: User, db: AsyncSession) -> Course:
    course = (
        await db.execute(
            select(Course).where(Course.id == course_id, Course.user_id == user.id)
        )
    ).scalar_one_or_none()
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")
    return course


async def _general_module(db: AsyncSession, course_id: int) -> Module:
    """Find-or-create the hidden 'Course files' container (is_general)."""
    general = (
        await db.execute(
            select(Module).where(
                Module.course_id == course_id, Module.is_general.is_(True)
            )
        )
    ).scalar_one_or_none()
    if general is None:
        general = Module(
            course_id=course_id, title="Course files", position=9999, is_general=True
        )
        db.add(general)
        await db.flush()
    return general


class CanvasItemOut(BaseModel):
    canvas_item_id: int
    type: str  # File | Page | Discussion | ExternalUrl | Assignment | Quiz | SubHeader…
    title: str
    content_id: int | None = None  # file id / discussion topic id
    page_url: str | None = None
    external_url: str | None = None
    html_url: str | None = None


class CanvasModuleOut(BaseModel):
    canvas_id: int
    name: str
    position: int
    items: list[CanvasItemOut]


class CanvasStructureOut(BaseModel):
    modules: list[CanvasModuleOut]
    pages: list[dict]  # standalone [{url, title}]
    discussions: list[dict]  # [{id, title}]
    has_syllabus: bool


async def _safe_get_all(path: str, params: dict | None = None) -> list:
    """Like _canvas_get_all but returns [] instead of raising — some courses
    restrict individual tabs (Modules/Pages/Discussions 403), and one locked
    section must not fail the whole sync."""
    try:
        return await _canvas_get_all(path, params)
    except (CanvasAuthError, CanvasRateLimited):
        raise  # an expired token / throttling is not "this tab is empty"
    except HTTPException:
        return []


@router.get("/courses/{canvas_course_id}/structure")
async def canvas_structure(canvas_course_id: int) -> CanvasStructureOut:
    """The course's Canvas tree — modules→items + standalone pages/discussions +
    a syllabus flag — for the sync picker. Resilient: a locked section is simply
    empty rather than failing the request."""
    async def syllabus() -> bool:
        try:
            course = await _canvas_get(
                f"/courses/{canvas_course_id}", {"include[]": "syllabus_body"}
            )
        except (CanvasAuthError, CanvasRateLimited):
            raise
        except HTTPException:
            return False
        return bool(isinstance(course, dict) and (course.get("syllabus_body") or "").strip())

    # Four independent reads — fetched together instead of one after another.
    raw, raw_pages, raw_discussions, has_syllabus = await asyncio.gather(
        _safe_get_all(f"/courses/{canvas_course_id}/modules", {"include[]": "items"}),
        _safe_get_all(f"/courses/{canvas_course_id}/pages"),
        _safe_get_all(f"/courses/{canvas_course_id}/discussion_topics"),
        syllabus(),
    )
    modules = [
        CanvasModuleOut(
            canvas_id=m["id"],
            name=m.get("name") or "Module",
            position=m.get("position") or 0,
            items=[
                CanvasItemOut(
                    canvas_item_id=it.get("id"),
                    type=it.get("type") or "",
                    title=it.get("title") or "(untitled)",
                    content_id=it.get("content_id"),
                    page_url=it.get("page_url"),
                    external_url=it.get("external_url"),
                    html_url=it.get("html_url"),
                )
                for it in (m.get("items") or [])
                if isinstance(it, dict) and it.get("id")
            ],
        )
        for m in raw
        if isinstance(m, dict) and m.get("id")
    ]
    pages = [
        {"url": p.get("url"), "title": p.get("title") or p.get("url")}
        for p in raw_pages
        if isinstance(p, dict) and p.get("url")
    ]
    discussions = [
        {"id": d.get("id"), "title": d.get("title") or "(untitled)"}
        for d in raw_discussions
        if isinstance(d, dict) and d.get("id")
    ]
    return CanvasStructureOut(
        modules=modules, pages=pages, discussions=discussions, has_syllabus=has_syllabus
    )


class SyncModulesIn(BaseModel):
    course_id: int  # Manabi course id
    modules: list[dict]  # [{canvas_id, name, position}]


@router.post("/sync-modules", dependencies=[Depends(require_csrf)])
async def sync_modules(
    data: SyncModulesIn,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Find-or-create a Manabi module per selected Canvas module (dedup by
    canvas_module_id). Returns the canvas→manabi id mapping."""
    course = await _owned_course(data.course_id, user, db)
    out: list[dict] = []
    for m in data.modules:
        cid = int(m["canvas_id"])
        module = (
            await db.execute(
                select(Module).where(
                    Module.course_id == course.id, Module.canvas_module_id == cid
                )
            )
        ).scalar_one_or_none()
        if module is None:
            module = Module(
                course_id=course.id,
                title=(m.get("name") or "Module")[:255],
                canvas_module_id=cid,
                position=m.get("position") or 0,
            )
            db.add(module)
            await db.flush()
        out.append({"canvas_id": cid, "module_id": module.id, "title": module.title})
    await db.commit()
    return out


class ImportPageIn(BaseModel):
    canvas_course_id: int
    page_url: str


@router.post("/modules/{module_id}/import-page", dependencies=[Depends(require_csrf)])
async def canvas_import_page(
    data: ImportPageIn,
    module: Module = Depends(get_owned_module),
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
):
    page = await _canvas_get(
        f"/courses/{data.canvas_course_id}/pages/{data.page_url}"
    )
    if not isinstance(page, dict):
        raise HTTPException(status_code=502, detail="Canvas page unavailable")
    doc, job = await import_html_as_document(
        db,
        user,
        module,
        title=page.get("title") or data.page_url,
        html=page.get("body") or "",
        source_url=page.get("html_url") or f"canvas:page:{data.page_url}",
    )
    await db.commit()
    return _doc_out(doc, job.id)


class ImportDiscussionIn(BaseModel):
    canvas_course_id: int
    topic_id: int


@router.post(
    "/modules/{module_id}/import-discussion", dependencies=[Depends(require_csrf)]
)
async def canvas_import_discussion(
    data: ImportDiscussionIn,
    module: Module = Depends(get_owned_module),
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
):
    topic = await _canvas_get(
        f"/courses/{data.canvas_course_id}/discussion_topics/{data.topic_id}"
    )
    if not isinstance(topic, dict):
        raise HTTPException(status_code=502, detail="Canvas discussion unavailable")
    doc, job = await import_html_as_document(
        db,
        user,
        module,
        title=topic.get("title") or f"Discussion {data.topic_id}",
        html=topic.get("message") or "",
        source_url=topic.get("html_url") or f"canvas:discussion:{data.topic_id}",
    )
    await db.commit()
    return _doc_out(doc, job.id)


class ImportSyllabusIn(BaseModel):
    canvas_course_id: int


@router.post("/courses/{course_id}/import-syllabus", dependencies=[Depends(require_csrf)])
async def canvas_import_syllabus(
    course_id: int,
    data: ImportSyllabusIn,
    user: User = Depends(get_default_user),
    db: AsyncSession = Depends(get_db),
):
    """Render the course syllabus into the hidden 'Course files' module."""
    course = await _owned_course(course_id, user, db)
    detail = await _canvas_get(
        f"/courses/{data.canvas_course_id}", {"include[]": "syllabus_body"}
    )
    body = (detail.get("syllabus_body") if isinstance(detail, dict) else None) or ""
    if not body.strip():
        raise HTTPException(status_code=404, detail="This course has no syllabus")
    module = await _general_module(db, course.id)
    doc, job = await import_html_as_document(
        db,
        user,
        module,
        title=f"{course.code} — Syllabus",
        html=body,
        source_url=f"canvas:syllabus:{data.canvas_course_id}",
    )
    await db.commit()
    return _doc_out(doc, job.id)
