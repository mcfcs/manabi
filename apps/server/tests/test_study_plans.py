"""Study plans: the AI-chosen mix and how a plan's own choices override it."""

from manabi_core.material_profile import profile_material

from manabi_server.services.study_plans import auto_mix, merge_mixes, plan_mix, section_mix

C_CODE = [
    "#include <stdio.h>\nint main() {\n int x = 3;\n printf(\"%d\", x);\n return 0;\n}\n"
    "char *p = s; while (*p) p++; int a[3]; a[0] = 1; p[2] = 0; for (i = 0; i < 3; i++) {"
] * 4
READING = [
    "Everyday politics is defined as the people embracing, complying with, adjusting and "
    "contesting norms. Three forms of politics are: official politics, advocacy politics, "
    "and everyday politics. Kerkvliet argues that peasants resist through small acts."
] * 4


def test_code_material_gets_an_output_heavy_mix():
    mix = auto_mix(profile_material(C_CODE))
    assert max(mix, key=mix.get) == "output"
    assert "mcq" in mix


def test_readings_get_comprehension_types_and_no_output():
    mix = auto_mix(profile_material(READING))
    assert "output" not in mix and "coding" not in mix
    assert mix["mcq"] >= mix.get("tf", 0)
    assert "identification" in mix


def test_a_plans_own_types_win_over_the_material():
    auto = {"output": 5, "mcq": 4}
    assert plan_mix(["essay", "mcq"], None, auto) == {"essay": 1.0, "mcq": 1.0}
    assert plan_mix(["essay", "mcq"], {"essay": 3, "mcq": 1}, auto) == {"essay": 3.0, "mcq": 1.0}
    assert plan_mix(None, None, auto) == auto


def test_merging_mixes_keeps_every_type():
    out = merge_mixes([{"output": 5, "mcq": 5}, {"mcq": 1, "identification": 1}])
    assert set(out) == {"output", "mcq", "identification"}
    assert out["mcq"] > out["output"]


def test_section_checks_drop_long_form_types():
    assert section_mix({"essay": 2, "coding": 1, "mcq": 3}) == {"mcq": 3}
    assert section_mix({"essay": 1}) == {"mcq": 3, "tf": 1, "identification": 1}
