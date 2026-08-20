"""Turn external HTML (a Canvas Page / discussion topic / syllabus) into a
first-class Manabi material: render the HTML to a PDF with LibreOffice, then
feed it through the normal document pipeline (Docling text → chunks →
embeddings → viewer → citations). Text is preserved even when Canvas-hosted
images (auth-gated) don't render; a plain-text PDF fallback guarantees the
content is never silently dropped."""

import asyncio
import html as _html
import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from manabi_core.models import Document, Job, Module, User
from sqlalchemy.ext.asyncio import AsyncSession

from manabi_server.config import get_settings

log = logging.getLogger("manabi_server")


def html_to_text(html_text: str) -> str:
    """HTML → plain text, keeping paragraph/line breaks. Shared by Canvas
    announcements and the HTML→PDF text fallback."""
    text = re.sub(r"(?i)<br\s*/?>", "\n", html_text or "")
    text = re.sub(r"(?i)</(p|div|li|h[1-6]|tr)>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "• ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = _html.unescape(text)
    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _soffice_to_pdf(source: Path, outdir: Path) -> bytes | None:
    """Convert a .html/.txt file to PDF via headless LibreOffice (same binary
    used for PPTX render). Returns the PDF bytes or None on failure."""
    settings = get_settings()
    outdir.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [
                settings.soffice_path,
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(outdir),
                str(source),
            ],
            check=True,
            capture_output=True,
            timeout=300,
        )
        produced = list(outdir.glob("*.pdf"))
        return produced[0].read_bytes() if produced else None
    except Exception:  # noqa: BLE001 — the caller falls back to a text PDF
        log.exception("soffice HTML→PDF failed for %s", source.name)
        return None


def render_html_to_pdf(html: str, title: str) -> bytes:
    """Render `html` to PDF (LibreOffice). Falls back to a plain-text PDF built
    from the stripped text so ingestion never loses the content. Blocking —
    call via asyncio.to_thread."""
    text = html_to_text(html)
    work = Path(tempfile.mkdtemp(prefix="manabi_html_"))
    try:
        doc = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            f"<title>{_html.escape(title)}</title></head><body>"
            f"<h1>{_html.escape(title)}</h1>{html}</body></html>"
        )
        src = work / "page.html"
        src.write_text(doc, encoding="utf-8")
        pdf = _soffice_to_pdf(src, work / "out")
        if pdf and pdf.startswith(b"%PDF"):
            return pdf
        # Fallback: plain text → PDF (soffice handles .txt too).
        txt = work / "page.txt"
        txt.write_text(f"{title}\n\n{text}", encoding="utf-8")
        pdf = _soffice_to_pdf(txt, work / "out2")
        if pdf and pdf.startswith(b"%PDF"):
            return pdf
        raise RuntimeError(
            "Could not render the Canvas content to PDF — is LibreOffice "
            "(soffice_path) installed and configured?"
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _safe_filename(title: str) -> str:
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", (title or "Canvas page")).strip()
    return (base[:120] or "Canvas page") + ".pdf"


async def import_html_as_document(
    db: AsyncSession,
    user: User,
    module: Module,
    *,
    title: str,
    html: str,
    source_url: str | None = None,
    ai_included: bool = True,
) -> tuple[Document, Job]:
    """Render HTML → PDF and ingest it as a full-pipeline Document. Does NOT
    commit (caller owns the transaction). Raises HTTPException 409 (duplicate)."""
    from manabi_server.api.documents import ingest_bytes  # avoid import cycle

    pdf = await asyncio.to_thread(render_html_to_pdf, html, title)
    return await ingest_bytes(
        db,
        user,
        module,
        filename=_safe_filename(title),
        ext="pdf",
        content=pdf,
        ai_included=ai_included,
        processing_mode="full",
        source_url=source_url,
    )
