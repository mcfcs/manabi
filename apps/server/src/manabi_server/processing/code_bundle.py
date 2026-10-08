"""Code materials: a course's demo programs, kept byte-for-byte.

A professor's demo page often links several files that only make sense
together (employee.h + teacher.h + teacher.cpp + methoddemo.cpp — the output
depends on all of them). They are stored as one plain-text material, a
"bundle": a marker line, then each file under a `//// FILE: name` line. The
structure stage turns every file into a heading ("File: teacher.h") and one
code element with its indentation intact, so chunks carry exact, fenced code.

Plain-text import splits at blank lines and strips each block, which loses
exactly what matters here (indentation, spacing), so bundles have their own
path. Pure; unit-tested.
"""

from __future__ import annotations

import io
import re
import zipfile

BUNDLE_SUFFIX = ".code.txt"
MARKER = "//// manabi code bundle"
_FILE_LINE = re.compile(r"^//// FILE: (.+)$", re.M)

CODE_FILE = re.compile(r"\.(c|cc|cpp|cxx|h|hh|hpp|py|lisp|lsp|scm|rkt|java|js|txt)$", re.I)
LANGUAGE = {
    "c": "c",
    "h": "c",
    "cc": "cpp",
    "cpp": "cpp",
    "cxx": "cpp",
    "hh": "cpp",
    "hpp": "cpp",
    "py": "python",
    "lisp": "lisp",
    "lsp": "lisp",
    "scm": "scheme",
    "rkt": "racket",
    "java": "java",
    "js": "javascript",
    "txt": "text",
}
MAX_FILE_BYTES = 200_000


def is_bundle_name(filename: str | None) -> bool:
    return (filename or "").lower().endswith(BUNDLE_SUFFIX)


def language_of(name: str) -> str:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return LANGUAGE.get(ext, "text")


def wanted(name: str) -> bool:
    """A source file (or a small input file a demo reads), not a build
    script, archive or document."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    return bool(CODE_FILE.search(base)) and not base.startswith(".")


def clean_code(text: str) -> str:
    """Normalise line endings and trailing spaces; never touch indentation."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).strip("\n") + "\n"


def make_bundle(files: list[tuple[str, str]]) -> str:
    parts = [MARKER]
    for name, code in files:
        parts.append(f"//// FILE: {name}")
        parts.append(clean_code(code).rstrip("\n"))
    return "\n".join(parts) + "\n"


def parse_bundle(text: str) -> list[tuple[str, str]] | None:
    """[(file name, code)] or None when the text is not a bundle."""
    if not text.startswith(MARKER):
        return None
    marks = list(_FILE_LINE.finditer(text))
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        code = text[m.end() : end].strip("\n")
        if code.strip():
            out.append((m.group(1).strip(), code + "\n"))
    return out


def files_from_zip(data: bytes) -> list[tuple[str, str]]:
    """The source files inside a zip, in name order (macOS resource forks,
    folders and binaries skipped)."""
    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in sorted(z.infolist(), key=lambda i: i.filename):
            name = info.filename
            if info.is_dir() or "__MACOSX" in name or not wanted(name):
                continue
            if info.file_size > MAX_FILE_BYTES:
                continue
            text = decode(z.read(info))
            if text is not None:
                out.append((name.rsplit("/", 1)[-1], text))
    return out


def decode(data: bytes) -> str | None:
    """Text of a source file, or None for binary content."""
    if b"\x00" in data[:4096]:
        return None
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return None


def order_files(files: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Headers first, then implementation files, then the file with main()
    last — the order a reader traces a multi-file demo in."""

    def rank(item: tuple[str, str]) -> tuple[int, str]:
        name, code = item
        if re.search(r"\bint\s+main\s*\(", code):
            return (2, name)
        if name.lower().endswith((".h", ".hpp", ".hh")):
            return (0, name)
        return (1, name)

    return sorted(files, key=rank)
