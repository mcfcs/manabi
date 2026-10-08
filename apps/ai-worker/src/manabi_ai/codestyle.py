"""The professor's code style, measured from a course's demo programs.

Generated code read like a style guide nobody in the course uses ("int
main(void) {", 4-space K&R, `int a = 5;`), while the professor writes `int
main()` with the brace on its own line, 3-space indents, declarations first
and assignments after (`int a;` … `a = 5;`), `class teacher:public employee`.
A student drilling output questions should see code that looks like the
exam's. This measures those habits from the course's own files and turns them
into a short style block plus two real excerpts for the generation prompts.
Pure; unit-tested.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

_FUNC_HEAD = re.compile(r"^[A-Za-z_][\w\s\*&:<>,]*\b[A-Za-z_]\w*\s*\([^;{}]*\)\s*(const)?\s*$")
_FUNC_HEAD_BRACE = re.compile(
    r"^[A-Za-z_][\w\s\*&:<>,]*\b[A-Za-z_]\w*\s*\([^;{}]*\)\s*(const)?\s*\{\s*$"
)
_CONTROL = re.compile(r"^\s*(if|for|while|switch|else if)\b")
_DECL_NO_INIT = re.compile(
    r"^\s*(?:unsigned\s+|const\s+|static\s+)*(int|char|float|double|long|short|bool)\s+\**\s*\w+(\s*\[[^\]]*\])?"
    r"(\s*,\s*\**\s*\w+(\s*\[[^\]]*\])?)*\s*;"
)
_DECL_INIT = re.compile(
    r"^\s*(?:unsigned\s+|const\s+|static\s+)*(int|char|float|double|long|short|bool)\s+\**\s*\w+(\s*\[[^\]]*\])?\s*="
)
_CLASS = re.compile(r"^\s*class\s+([A-Za-z_]\w*)\s*(:\s*\w+\s+\w+)?")


@dataclass
class Style:
    files: int
    indent: int | None
    func_brace_own_line: bool | None
    control_brace_own_line: bool | None
    main: str | None
    space_after_keyword: bool | None
    declare_then_assign: bool | None
    endl: bool | None
    using_std: bool | None
    class_lowercase: bool | None
    inherit_tight: bool | None
    returns_zero: bool | None


def _majority(yes: int, no: int, margin: float = 0.6) -> bool | None:
    total = yes + no
    if total < 2:
        return None
    share = yes / total
    if share >= margin:
        return True
    if share <= 1 - margin:
        return False
    return None


def _indent_unit(lines: list[str]) -> int | None:
    deltas: Counter[int] = Counter()
    prev = None
    for line in lines:
        if not line.strip() or line.lstrip().startswith(("//", "/*", "*", "#")):
            continue
        lead = line[: len(line) - len(line.lstrip(" "))]
        if "\t" in line[: len(line) - len(line.lstrip())]:
            prev = None
            continue
        n = len(lead)
        if prev is not None and 2 <= n - prev <= 8:
            deltas[n - prev] += 1
        prev = n
    return deltas.most_common(1)[0][0] if deltas else None


def measure(sources: list[str]) -> Style:
    """Habits across C/C++ source files (other languages are ignored)."""
    all_lines: list[str] = []
    fb_own = fb_same = cb_own = cb_same = 0
    mains: Counter[str] = Counter()
    kw_space = kw_tight = 0
    decl_bare = decl_init = 0
    endl = newline = 0
    using = cout_files = 0
    lower = upper = 0
    tight = spaced = 0
    ret0 = mains_seen = 0
    for src in sources:
        lines = src.split("\n")
        all_lines.extend(lines)
        stripped = [ln.strip() for ln in lines]
        for i, s in enumerate(stripped):
            nxt = stripped[i + 1] if i + 1 < len(stripped) else ""
            if _FUNC_HEAD.match(s) and not _CONTROL.match(s) and nxt == "{":
                fb_own += 1
            elif _FUNC_HEAD_BRACE.match(s) and not _CONTROL.match(s):
                fb_same += 1
            if _CONTROL.match(s) and not s.endswith(";"):
                if s.endswith("{"):
                    cb_same += 1
                elif nxt == "{":
                    cb_own += 1
            m = re.match(r"^(int|void)\s+main\s*\(([^)]*)\)", s)
            if m:
                mains[f"{m.group(1)} main({m.group(2).strip()})"] += 1
            kw_space += len(re.findall(r"\b(?:if|for|while|switch) \(", s))
            kw_tight += len(re.findall(r"\b(?:if|for|while|switch)\(", s))
            if _DECL_INIT.match(s) and "for" not in s[:4]:
                decl_init += 1
            elif _DECL_NO_INIT.match(s):
                decl_bare += 1
            if "cout" in s:
                endl += s.count("endl")
                newline += s.count("\\n")
            cm = _CLASS.match(s)
            if cm and not s.endswith(";"):
                if cm.group(1)[0].islower():
                    lower += 1
                else:
                    upper += 1
                if cm.group(2):
                    if re.search(r"\w:(public|private|protected)\b", s):
                        tight += 1
                    else:
                        spaced += 1
        text = "\n".join(lines)
        if "cout" in text:
            cout_files += 1
            if "using namespace std" in text:
                using += 1
        if re.search(r"\bint\s+main\s*\(", text):
            mains_seen += 1
            body = text[re.search(r"\bint\s+main\s*\(", text).start() :]
            if re.search(r"return\s+0\s*;", body):
                ret0 += 1
    return Style(
        files=len(sources),
        indent=_indent_unit(all_lines),
        func_brace_own_line=_majority(fb_own, fb_same),
        control_brace_own_line=_majority(cb_own, cb_same),
        main=mains.most_common(1)[0][0] if mains else None,
        space_after_keyword=_majority(kw_space, kw_tight),
        declare_then_assign=_majority(decl_bare, decl_init, margin=0.55),
        endl=_majority(endl, newline),
        using_std=_majority(using, cout_files - using) if cout_files else None,
        class_lowercase=_majority(lower, upper),
        inherit_tight=_majority(tight, spaced),
        returns_zero=_majority(ret0, mains_seen - ret0) if mains_seen else None,
    )


def rules(style: Style) -> list[str]:
    out: list[str] = []
    if style.indent:
        out.append(f"Indent with {style.indent} spaces per level.")
    if style.func_brace_own_line is True:
        out.append("Put a function's opening brace on its own line under the signature.")
    elif style.func_brace_own_line is False:
        out.append("Put a function's opening brace at the end of the signature line.")
    if style.control_brace_own_line is False:
        out.append("For if/for/while, the opening brace ends the line: `for (...) {`.")
    elif style.control_brace_own_line is True:
        out.append("For if/for/while, the opening brace goes on its own line.")
    if style.main:
        out.append(f"Write main as `{style.main}`.")
    if style.space_after_keyword is False:
        out.append("No space between a keyword and its parenthesis: `for(`, `if(`.")
    elif style.space_after_keyword is True:
        out.append("One space between a keyword and its parenthesis: `for (`, `if (`.")
    if style.declare_then_assign:
        out.append(
            "Declare variables at the top of the function without initialising them "
            "(`int a, b;` or `int *p;`), then assign on later lines (`a = 5;`)."
        )
    if style.endl is True:
        out.append("In C++, end output lines with `<< endl`.")
    if style.using_std:
        out.append("In C++, write `using namespace std;` after the includes.")
    if style.class_lowercase:
        out.append("Class names are lowercase (`class employee`).")
    if style.inherit_tight:
        out.append("Write inheritance without spaces: `class teacher:public employee`.")
    if style.returns_zero is True:
        out.append("End main with `return 0;`.")
    elif style.returns_zero is False:
        out.append("main usually ends without `return 0;`.")
    return out


def _excerpt_score(code: str) -> float:
    lines = [ln for ln in code.split("\n") if ln.strip()]
    if not 8 <= len(lines) <= 30 or not re.search(r"\bmain\s*\(", code):
        return -1
    prints = len(re.findall(r"printf|cout", code))
    # Tab-indented lines contradict the measured space indent beside them.
    tabbed = sum(1 for ln in lines if ln[: len(ln) - len(ln.lstrip())].count("\t"))
    return prints * 2 - abs(len(lines) - 18) * 0.2 - tabbed * 3


def pick_excerpts(files: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """One short, output-heavy C program and one C++ program, verbatim."""
    picks = []
    for want_cpp in (False, True):
        pool = [
            (n, c)
            for n, c in files
            if n.lower().endswith((".cpp", ".cc", ".cxx")) == want_cpp
            and n.lower().endswith((".c", ".cpp", ".cc", ".cxx"))
        ]
        pool = [p for p in pool if _excerpt_score(p[1]) > 0]
        if pool:
            picks.append(max(pool, key=lambda p: _excerpt_score(p[1])))
    return picks


def style_block(files: list[tuple[str, str]]) -> str:
    """The prompt block for a course with demo code, or "" without any."""
    c_like = [
        (n, c) for n, c in files if n.lower().endswith((".c", ".h", ".cpp", ".cc", ".hpp", ".cxx"))
    ]
    if not c_like:
        return ""
    style = measure([c for _n, c in c_like])
    lines = rules(style)
    excerpts = pick_excerpts(c_like)
    if not lines and not excerpts:
        return ""
    out = [
        "",
        "COURSE CODE STYLE — measured from the professor's own demo programs "
        f"({len(c_like)} files). Every program you write must look like his:",
    ]
    out += [f"- {r}" for r in lines]
    out.append(
        "- Prefer his demos as the basis of code questions: keep a demo's structure, "
        "names and style, change one value, line or call, and ask exactly what it prints."
    )
    for name, code in excerpts:
        body = code.strip("\n").rstrip()
        out.append(f"\nHis style, verbatim ({name.rsplit('/', 1)[-1]}):\n```\n{body}\n```")
    return "\n".join(out) + "\n"
