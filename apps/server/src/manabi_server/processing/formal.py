"""Formal-language answers — grammars, regular expressions, DFAs — checked by
membership, not by matching the key's wording.

Two answers to "write a grammar for { aⁿbⁿ }" can look nothing alike and both
be right, so an answer is compared with the reference on every string over
the alphabet up to a length bound: the same strings must be accepted. The
shortest disagreement is the feedback ("aab should be rejected"). Bounded, so
not a proof of equivalence — but at lengths a course exercise lives at it
finds every mistake a student makes in practice.

Formats (lenient, as written in class):
  grammar  `S -> a S b | ε` one nonterminal per line; also `→`, `::=`;
           ε / eps / epsilon / an empty alternative; nonterminals are symbols
           that have rules; `aSb` without spaces is read one symbol per char.
  regex    concatenation, `|` union, `*` `+` `?`, parentheses, `ε`.
  dfa      `start: q0`, `accept: q1, q2`, then transitions `q0 a q1`
           (also `q0 -a-> q1`); a missing transition rejects.
Pure; unit-tested.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field

EPSILON = {"ε", "eps", "epsilon", "λ", "''", '""'}
MAX_STRINGS = 4000


class FormatError(ValueError):
    """The answer could not be read; the message says where."""


# ── Grammars ──────────────────────────────────────────────────────────────


@dataclass
class Grammar:
    start: str
    rules: dict[str, list[tuple[str, ...]]] = field(default_factory=dict)

    @property
    def terminals(self) -> set[str]:
        return {
            s for alts in self.rules.values() for alt in alts for s in alt if s not in self.rules
        }


_ARROW = re.compile(r"\s*(?:->|→|::=|=>)\s*")


def parse_grammar(text: str) -> Grammar:
    lines = [ln.strip() for ln in (text or "").replace("\r", "").split("\n")]
    lines = [ln for ln in lines if ln and not ln.startswith(("#", "//"))]
    if not lines:
        raise FormatError("the grammar is empty")
    raw: list[tuple[str, list[str]]] = []
    for n, line in enumerate(lines, start=1):
        parts = _ARROW.split(line, maxsplit=1)
        if len(parts) != 2 or not parts[0].strip():
            raise FormatError(f"line {n}: expected `A -> …`, got {line!r}")
        lhs = parts[0].strip()
        if " " in lhs:
            raise FormatError(f"line {n}: the left side must be one nonterminal, got {lhs!r}")
        raw.append((lhs, [a.strip() for a in parts[1].split("|")]))
    nonterminals = {lhs for lhs, _ in raw}
    g = Grammar(start=raw[0][0])
    for lhs, alts in raw:
        for alt in alts:
            g.rules.setdefault(lhs, []).append(_symbols(alt, nonterminals))
    return g


def _symbols(alt: str, nonterminals: set[str]) -> tuple[str, ...]:
    if alt in EPSILON or alt == "":
        return ()
    if " " in alt:
        tokens = alt.split()
    else:
        # "aSb": split into known nonterminals (longest first) and characters.
        tokens, i = [], 0
        names = sorted(nonterminals, key=len, reverse=True)
        while i < len(alt):
            match = next((nt for nt in names if alt.startswith(nt, i)), None)
            if match:
                tokens.append(match)
                i += len(match)
            else:
                tokens.append(alt[i])
                i += 1
    return tuple(t for t in tokens if t not in EPSILON)


def grammar_accepts(g: Grammar, word: tuple[str, ...]) -> bool:
    """Earley recognition (handles ε-rules and left recursion)."""
    nullable = _nullable(g)
    # item: (lhs, alt_index, dot, origin)
    chart: list[set[tuple[str, int, int, int]]] = [set() for _ in range(len(word) + 1)]
    for ai in range(len(g.rules.get(g.start, []))):
        chart[0].add((g.start, ai, 0, 0))
    for i in range(len(word) + 1):
        agenda = list(chart[i])
        while agenda:
            lhs, ai, dot, origin = agenda.pop()
            alt = g.rules[lhs][ai]
            if dot < len(alt):
                sym = alt[dot]
                if sym in g.rules:  # predict
                    for bi in range(len(g.rules[sym])):
                        item = (sym, bi, 0, i)
                        if item not in chart[i]:
                            chart[i].add(item)
                            agenda.append(item)
                    if sym in nullable:  # Aycock–Horspool: skip a nullable symbol
                        item = (lhs, ai, dot + 1, origin)
                        if item not in chart[i]:
                            chart[i].add(item)
                            agenda.append(item)
                elif i < len(word) and word[i] == sym:  # scan
                    chart[i + 1].add((lhs, ai, dot + 1, origin))
            else:  # complete
                for plhs, pai, pdot, porigin in list(chart[origin]):
                    palt = g.rules[plhs][pai]
                    if pdot < len(palt) and palt[pdot] == lhs:
                        item = (plhs, pai, pdot + 1, porigin)
                        if item not in chart[i]:
                            chart[i].add(item)
                            agenda.append(item)
    return any(
        lhs == g.start and dot == len(g.rules[lhs][ai]) and origin == 0
        for lhs, ai, dot, origin in chart[len(word)]
    )


def _nullable(g: Grammar) -> set[str]:
    out: set[str] = set()
    changed = True
    while changed:
        changed = False
        for lhs, alts in g.rules.items():
            if lhs not in out and any(all(s in out for s in alt) for alt in alts):
                out.add(lhs)
                changed = True
    return out


# ── Regular expressions ───────────────────────────────────────────────────

_REGEX_OK = re.compile(r"^[A-Za-z0-9()|*+?ε∅ ]+$")


def compile_regex(text: str) -> re.Pattern:
    e = (text or "").strip().strip("`").replace(" ", "")
    if not e:
        raise FormatError("the regular expression is empty")
    if not _REGEX_OK.match(e):
        bad = sorted(set(re.sub(r"[A-Za-z0-9()|*+?ε∅]", "", e)))
        raise FormatError(f"unsupported symbol(s) {' '.join(bad)} — use letters, | * + ? ( ) ε")
    e = e.replace("ε", "(?:)").replace("∅", "(?!)")
    try:
        return re.compile(e)
    except re.error as exc:
        raise FormatError(f"the regular expression does not parse: {exc}") from exc


# ── DFAs ──────────────────────────────────────────────────────────────────


@dataclass
class DFA:
    start: str
    accept: set[str]
    delta: dict[tuple[str, str], str]


_TRANSITION = re.compile(r"^(\S+)\s*(?:-+\s*(\S+?)\s*-+>|\s(\S+)\s)\s*(\S+)$")


def parse_dfa(text: str) -> DFA:
    start, accept, delta = None, set(), {}
    for n, line in enumerate((text or "").replace("\r", "").split("\n"), start=1):
        line = line.strip()
        if not line or line.startswith(("#", "//")):
            continue
        low = line.lower()
        if low.startswith("start"):
            start = line.split(":", 1)[-1].strip()
            continue
        if low.startswith(("accept", "final")):
            accept |= {s.strip() for s in line.split(":", 1)[-1].split(",") if s.strip()}
            continue
        m = _TRANSITION.match(line)
        if not m:
            raise FormatError(f"line {n}: expected `q0 a q1`, got {line!r}")
        src, sym, dst = m.group(1), m.group(2) or m.group(3), m.group(4)
        if (src, sym) in delta and delta[(src, sym)] != dst:
            raise FormatError(f"line {n}: two transitions from {src} on {sym} — not deterministic")
        delta[(src, sym)] = dst
    if not start:
        raise FormatError("missing `start: <state>`")
    if not accept:
        raise FormatError("missing `accept: <state>, …`")
    return DFA(start, accept, delta)


def dfa_accepts(d: DFA, word: tuple[str, ...]) -> bool:
    state = d.start
    for sym in word:
        state = d.delta.get((state, sym))
        if state is None:
            return False
    return state in d.accept


# ── One interface ────────────────────────────────────────────────────────


def recognizer(kind: str, text: str):
    """A function word(tuple of symbols) -> bool, or FormatError."""
    if kind == "grammar":
        g = parse_grammar(text)
        return lambda w: grammar_accepts(g, w)
    if kind == "regex":
        p = compile_regex(text)
        return lambda w: bool(p.fullmatch("".join(w)))
    if kind == "dfa":
        d = parse_dfa(text)
        return lambda w: dfa_accepts(d, w)
    raise FormatError(f"unknown answer kind {kind!r}")


def all_words(alphabet: list[str], max_len: int | None = None) -> list[tuple[str, ...]]:
    """Every word up to the longest length that keeps the set under
    MAX_STRINGS (alphabet of 2 → length 11, of 3 → 7)."""
    alphabet = sorted(dict.fromkeys(alphabet))
    if not alphabet:
        return [()]
    if max_len is None:
        max_len, total = 0, 1
        while total + len(alphabet) ** (max_len + 1) <= MAX_STRINGS and max_len < 14:
            max_len += 1
            total += len(alphabet) ** max_len
    out: list[tuple[str, ...]] = []
    for n in range(max_len + 1):
        out.extend(itertools.product(alphabet, repeat=n))
    return out


def show(word: tuple[str, ...]) -> str:
    return "".join(word) if word else "ε"


@dataclass
class TheoryVerdict:
    verdict: str  # accepted|wrong|format_error
    checked: int = 0
    max_len: int = 0
    error: str = ""
    # up to 5 disagreements, shortest first: {"string", "expected"}
    mismatches: list[dict] = field(default_factory=list)


def check(kind: str, answer: str, tests: list[dict]) -> TheoryVerdict:
    """Compare the answer's membership with the stored expectations
    ({"s": "aab", "accept": false} — computed from the reference)."""
    try:
        accepts = recognizer(kind, answer)
    except FormatError as exc:
        return TheoryVerdict("format_error", error=str(exc))
    mismatches = []
    for t in tests:
        word = tuple(t["s"]) if t["s"] != "ε" else ()
        if accepts(word) != bool(t["accept"]):
            mismatches.append({"string": t["s"], "expected": bool(t["accept"])})
            if len(mismatches) >= 5:
                break
    longest = max((len(t["s"]) if t["s"] != "ε" else 0 for t in tests), default=0)
    return TheoryVerdict(
        "wrong" if mismatches else "accepted", len(tests), longest, mismatches=mismatches
    )


def build_tests(kind: str, reference: str, alphabet: list[str]) -> tuple[list[dict], str]:
    """Expectations for every word up to the bound, from the reference
    answer. Returns (tests, problem) — problem is "" when usable."""
    try:
        accepts = recognizer(kind, reference)
    except FormatError as exc:
        return [], f"the reference answer does not parse: {exc}"
    symbols = [a for a in alphabet if a and a not in EPSILON]
    if not symbols or any(len(a) != 1 for a in symbols):
        return [], "the alphabet must be single characters"
    if kind == "grammar":
        extra = parse_grammar(reference).terminals - set(symbols)
        if extra:
            return [], f"the reference grammar uses symbols outside the alphabet: {sorted(extra)}"
    tests = [{"s": show(w), "accept": accepts(w)} for w in all_words(symbols)]
    yes = sum(1 for t in tests if t["accept"])
    if yes == 0:
        return [], "the reference accepts no string up to the bound"
    if yes == len(tests):
        return [], "the reference accepts every string — nothing to tell apart"
    return tests, ""
