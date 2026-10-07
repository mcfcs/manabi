"""Pure helpers for planning and checking a quiz.

A quiz is planned before it is written: the material is turned into a list of
distinct targets (topic + skill), each target is given a question type, and
only then is a question written per target. Asking for "20 questions" in one
breath produced 20 copies of the same `p[k]` / `%s` question; asking for one
question per distinct target does not.

After writing, objective questions are solved blind — by a fresh call that
never sees the key — and compared with the key. Nothing here talks to a model
or a database, so all of it is unit-tested.
"""

import itertools
import math
import re
import unicodedata

# Types that only make sense when the target involves code.
CODE_ONLY_TYPES = ("output", "coding")

# Questions a blind solver can answer and we can compare mechanically.
AUDITABLE_TYPES = ("mcq", "tf", "identification", "short")


# ── Allocation ───────────────────────────────────────────────────────────


def allocate(total: int, weights: dict, minimum: int = 0) -> dict:
    """Split `total` across keys in proportion to `weights` (largest
    remainder), giving every key at least `minimum` while the total allows.
    Deterministic: ties go to the key listed first."""
    keys = [k for k, w in weights.items() if w > 0]
    if total <= 0 or not keys:
        return {k: 0 for k in weights}
    floor_each = minimum if minimum * len(keys) <= total else 0
    rest = total - floor_each * len(keys)
    wsum = sum(weights[k] for k in keys)
    raw = {k: rest * weights[k] / wsum for k in keys}
    out = {k: floor_each + math.floor(raw[k]) for k in keys}
    left = total - sum(out.values())
    order = sorted(keys, key=lambda k: (-(raw[k] - math.floor(raw[k])), keys.index(k)))
    for k in order[:left]:
        out[k] += 1
    return {k: out.get(k, 0) for k in weights}


def normalize_mix(types: list[str], type_mix: dict | None) -> dict[str, float]:
    """Requested type weights restricted to the requested types; uniform when
    no mix (or an unusable one) is given."""
    if type_mix:
        mix = {t: float(type_mix.get(t, 0) or 0) for t in types}
        if sum(mix.values()) > 0:
            return {t: w for t, w in mix.items() if w > 0}
    return {t: 1.0 for t in types}


def assign_types(code_flags: list[bool], mix: dict[str, float]) -> list[str]:
    """One question type per target. Code-only types (output, coding) go only
    to targets that involve code; when there are too few of those, the
    shortfall moves to the other types in proportion. Returns a list aligned
    with `code_flags`."""
    n = len(code_flags)
    if n == 0:
        return []
    counts = allocate(n, mix)
    n_code = sum(1 for f in code_flags if f)
    code_types = [t for t in mix if t in CODE_ONLY_TYPES]
    other_types = [t for t in mix if t not in CODE_ONLY_TYPES]
    want_code = sum(counts[t] for t in code_types)
    # Not enough code targets: cap code types and hand the rest to the others
    # (when every requested type is code-only, keep them anyway — the model
    # can still write code for a theory target).
    if want_code > n_code and other_types:
        capped = allocate(n_code, {t: mix[t] for t in code_types}) if code_types else {}
        spill = want_code - n_code
        extra = allocate(spill, {t: mix[t] for t in other_types})
        counts = {
            **{t: capped.get(t, 0) for t in code_types},
            **{t: counts[t] + extra[t] for t in other_types},
        }
    # Hand out: code types first to code targets, everything else after.
    pool_code = list(itertools.chain.from_iterable([t] * counts[t] for t in code_types))
    pool_other = list(itertools.chain.from_iterable([t] * counts[t] for t in other_types))
    # Interleave the "other" pool so mcq/tf/... are spread, not clumped.
    pool_other = _interleave(pool_other, other_types)
    out: list[str | None] = [None] * n
    for i, flag in enumerate(code_flags):
        if flag and pool_code:
            out[i] = pool_code.pop(0)
    for i in range(n):
        if out[i] is None:
            out[i] = pool_other.pop(0) if pool_other else (pool_code.pop(0) if pool_code else None)
    fallback = other_types[0] if other_types else code_types[0]
    return [t or fallback for t in out]


def _interleave(pool: list[str], order: list[str]) -> list[str]:
    buckets = {t: [x for x in pool if x == t] for t in order}
    out: list[str] = []
    while any(buckets.values()):
        for t in order:
            if buckets[t]:
                out.append(buckets[t].pop())
    return out


# ── Recognising code questions ───────────────────────────────────────────

_FENCE = re.compile(r"```[A-Za-z0-9_+#-]*[ \t]*\n.*?\S.*?```", re.DOTALL)
_ASKS_OUTPUT = re.compile(
    r"\b(?:outputs?|print(?:s|ed)?|display(?:s|ed)?|cout|printf|console|screen|shown)\b",
    re.I,
)


def has_code(prompt: str) -> bool:
    return bool(_FENCE.search(prompt or ""))


def executable_check_applies(qtype: str, prompt: str) -> bool:
    """True when the app server will settle this question by running its
    code (so a blind model solve would only add noise)."""
    if not has_code(prompt):
        return False
    if qtype == "output":
        return True
    if qtype in ("mcq", "short"):
        return bool(_ASKS_OUTPUT.search(_FENCE.sub(" ", prompt or "")))
    return False


# ── Comparing a blind solve with the key ─────────────────────────────────


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"[^\w\s*|+()ε]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def fuzzy_equal(a: str, b: str) -> bool:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    if na == nb or (len(nb) > 3 and nb in na) or (len(na) > 3 and na in nb):
        return True
    ta, tb = na.split(), set(nb.split())
    overlap = sum(1 for t in ta if t in tb)
    return overlap / max(len(ta), len(tb)) >= 0.6


# Formal regular expressions as courses write them: concatenation, |, *, +,
# parentheses, ε. Python's `re` reads the same notation once ε is "" and the
# alphabet is literal characters.
_FORMAL_REGEX = re.compile(r"^[A-Za-z0-9()|*+ε∅ ]{1,80}$")


def _to_python_regex(expr: str) -> str | None:
    e = (expr or "").strip().strip("`").replace(" ", "")
    if not e or not _FORMAL_REGEX.match(e) or "∅" in e:
        return None
    # A bare "ε" alternative or group becomes the empty string.
    e = e.replace("ε", "")
    try:
        re.compile(e)
    except re.error:
        return None
    return e


def regex_equivalent(a: str, b: str, max_len: int = 7) -> bool | None:
    """Do two formal regexes denote the same language? Brute force over every
    string up to `max_len` on their combined alphabet. None when either does
    not read as a formal regex (then the caller falls back to text compare)."""
    pa, pb = _to_python_regex(a), _to_python_regex(b)
    if pa is None or pb is None:
        return None
    alphabet = sorted(set(re.sub(r"[()|*+]", "", pa + pb)))
    if not alphabet or len(alphabet) > 4:
        return None
    ra, rb = re.compile(pa), re.compile(pb)
    for n in range(max_len + 1):
        for chars in itertools.product(alphabet, repeat=n):
            w = "".join(chars)
            if bool(ra.fullmatch(w)) != bool(rb.fullmatch(w)):
                return False
    return True


def answers_agree(qtype: str, answer: dict, solved: dict) -> bool:
    """Does a blind solve match the stored key? `solved` carries the solver's
    answer_option / answer_bool / answer_text."""
    kind = (answer or {}).get("kind", qtype)
    if kind == "mcq":
        return solved.get("answer_option") == answer.get("correct_option")
    if kind == "tf":
        return bool(solved.get("answer_bool")) == bool(answer.get("value"))
    key = answer.get("text") or ""
    got = solved.get("answer_text") or ""
    eq = regex_equivalent(key, got)
    if eq is not None:
        return eq
    return fuzzy_equal(key, got)
