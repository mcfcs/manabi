"""Study plans: scope resolution and the "let the AI choose" test mix.

A plan fixes modules, optionally a subset of their materials, question types
and a focus. Every test generated for a plan inherits those unless the request
overrides them. When the plan leaves types blank, the mix is chosen from the
material itself (material_profile): code-heavy modules get mostly
predict-the-output and code-reading questions, readings get comprehension and
identification, with enumeration/essay only where the material supports them.
Deterministic, so the choice is instant and the same material always gets the
same recommendation.
"""

from __future__ import annotations

from manabi_core.material_profile import MaterialProfile

# Types an AI-chosen mix may use. Coding/essay are opt-in only when the
# material signals them; short is folded into identification for readings.
_CODE_MIX = {"output": 5, "mcq": 4, "tf": 1, "identification": 1}
_READING_MIX = {"mcq": 5, "tf": 2, "identification": 3}

# Section checks are four quick questions: objective types only.
SECTION_TYPES = ("mcq", "tf", "identification", "output", "short")


def auto_mix(profile: MaterialProfile) -> dict[str, float]:
    """The question mix suited to one body of material."""
    rec = set(profile.recommended_types)
    if profile.language:
        mix: dict[str, float] = dict(_CODE_MIX)
        if "coding" in rec:
            mix["coding"] = 1
        return mix
    mix = dict(_READING_MIX)
    if "enumeration" in rec:
        mix["enumeration"] = 1
    if "essay" in rec:
        mix["essay"] = 1
    return mix


def merge_mixes(mixes: list[dict[str, float]]) -> dict[str, float]:
    """Combine per-module mixes for a cross-module exam (average weights)."""
    out: dict[str, float] = {}
    for m in mixes:
        total = sum(m.values()) or 1
        for t, w in m.items():
            out[t] = out.get(t, 0) + w / total
    n = len(mixes) or 1
    return {t: round(10 * w / n, 2) for t, w in out.items() if w > 0}


def plan_mix(
    types: list[str] | None, type_mix: dict | None, auto: dict[str, float]
) -> dict[str, float]:
    """The mix a plan's test uses: the plan's explicit types (weighted by its
    type_mix when given, else evenly), or the material's own mix."""
    if types:
        if type_mix:
            mix = {t: float(type_mix.get(t, 0) or 0) for t in types}
            mix = {t: w for t, w in mix.items() if w > 0}
            if mix:
                return mix
        return {t: 1.0 for t in types}
    return auto


def section_mix(mix: dict[str, float]) -> dict[str, float]:
    """A section check keeps only the quick objective types of a mix."""
    out = {t: w for t, w in mix.items() if t in SECTION_TYPES}
    return out or {"mcq": 3, "tf": 1, "identification": 1}
