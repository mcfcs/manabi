"""File storage under FILE_STORAGE_ROOT.

All paths are built from server-generated ids/uuids — never from
user-controlled strings. `storage_path`-style values persisted in the DB are
RELATIVE to the storage root so the root can move.
"""

import logging
import shutil
import uuid
from collections.abc import Iterable
from pathlib import Path

from manabi_server.config import get_settings

log = logging.getLogger("manabi.files")


def storage_root() -> Path:
    root = Path(get_settings().file_storage_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def resolve(rel_path: str) -> Path:
    """Resolve a DB-stored relative path, refusing anything outside the root."""
    root = storage_root()
    path = (root / rel_path).resolve()
    if not path.is_relative_to(root):
        raise ValueError("path escapes storage root")
    return path


def new_original_path(extension: str) -> str:
    assert extension in ("pdf", "pptx", "txt")
    return f"originals/{uuid.uuid4().hex}.{extension}"


def render_path(document_id: int, page_no: int) -> str:
    return f"renders/{document_id}/p{page_no}.png"


def thumb_path(document_id: int, page_no: int) -> str:
    return f"thumbs/{document_id}/p{page_no}.png"


def asset_path(document_id: int, name: str) -> str:
    return f"assets/{document_id}/{name}"


def note_asset_path(note_id: int, extension: str) -> str:
    assert extension in ("png", "jpg", "gif", "webp")
    return f"note_assets/{note_id}/{uuid.uuid4().hex}.{extension}"


def delete_note_files(note_id: int) -> None:
    shutil.rmtree(resolve(f"note_assets/{note_id}"), ignore_errors=True)


def course_cover_path(course_id: int, extension: str) -> str:
    assert extension in ("png", "jpg", "gif", "webp")
    return f"course_covers/{course_id}/{uuid.uuid4().hex}.{extension}"


def delete_course_files(course_id: int) -> None:
    shutil.rmtree(resolve(f"course_covers/{course_id}"), ignore_errors=True)


def normalized_path(document_id: int) -> str:
    """Spread-split PDF the extraction pipeline reads instead of the original.
    Keyed per-document (not per content-hash) so the same file in two modules
    can't share — and delete — one another's normalized artifact."""
    return f"normalized/{document_id}.pdf"


def write_atomic(rel_path: str, data: bytes) -> None:
    target = resolve(rel_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(target)


def delete_document_files(document_id: int, original_rel: str) -> None:
    """Every byte a document owns. `parse-cache/` is deliberately untouched: it
    is keyed by content hash and shared between identical uploads, so removing
    an entry here would evict another document's cache."""
    for rel in (f"renders/{document_id}", f"thumbs/{document_id}", f"assets/{document_id}"):
        shutil.rmtree(resolve(rel), ignore_errors=True)
    resolve(original_rel).unlink(missing_ok=True)
    resolve(normalized_path(document_id)).unlink(missing_ok=True)


def delete_files_for_documents(rows: Iterable[tuple[int, str]]) -> int:
    """Best-effort cleanup for a batch of (document_id, storage_path). Used
    where documents are removed by an FK cascade, which the database performs
    without ever telling the filesystem. Never raises: the rows are already
    gone, and a missing file must not turn into a failed request."""
    n = 0
    for document_id, storage_path in rows:
        try:
            delete_document_files(document_id, storage_path)
            n += 1
        except OSError as exc:  # noqa: PERF203 — one bad path must not stop the rest
            log.warning("could not delete files for document %s: %s", document_id, exc)
    return n
