"""Executing the code is the only thing that makes an `output` question true
rather than probably true. These tests use the real toolchain — if they pass,
verification genuinely works on this machine."""

import pytest

from manabi_server.processing.code_exec import (
    Snippet,
    c_compiler,
    execute,
    extract_snippet,
    normalize_output,
    outputs_match,
)

# The exact question qwen3.5:27b got wrong, verbatim.
POINTER_QUESTION = """Consider the following code involving an array of pointers.

```c
char *sentence = "the quick brown fox";
char *ptrs[3];
ptrs[0] = sentence + 5;
ptrs[1] = sentence + 1;
ptrs[2] = sentence + 8;
printf("%s\\n", ptrs[0]);
```
"""


def test_it_finds_the_c_block():
    s = extract_snippet(POINTER_QUESTION)
    assert s is not None
    assert s.lang == "c"
    assert "sentence + 5" in s.source


def test_a_prose_only_question_has_nothing_to_run():
    assert extract_snippet("What does the %s specifier do?") is None


def test_an_unsupported_language_is_left_to_the_model():
    assert extract_snippet("```rust\nfn main(){}\n```") is None


@pytest.mark.skipif(c_compiler() is None, reason="no C compiler")
def test_the_real_answer_to_the_question_the_model_got_wrong():
    # The model answered "quick brown fox" — the substring from index 4.
    # sentence+5 is index 5, so the program prints "uick brown fox".
    snippet = extract_snippet(POINTER_QUESTION)
    assert snippet is not None
    r = execute(snippet)
    assert r.ok, r.error
    assert normalize_output(r.stdout) == "uick brown fox"
    assert not outputs_match("quick brown fox", r.stdout)


@pytest.mark.skipif(c_compiler() is None, reason="no C compiler")
def test_a_fragment_without_main_is_wrapped_so_it_compiles():
    # Questions quote a fragment; none of them carry includes or a main.
    r = execute(Snippet("c", 'int n = 7; printf("%d\\n", n * 6);'))
    assert r.ok, r.error
    assert normalize_output(r.stdout) == "42"


@pytest.mark.skipif(c_compiler() is None, reason="no C compiler")
def test_a_snippet_that_brings_its_own_main_is_not_double_wrapped():
    src = '#include <stdio.h>\nint main(void){ printf("hi\\n"); return 0; }'
    r = execute(Snippet("c", src))
    assert r.ok, r.error
    assert normalize_output(r.stdout) == "hi"


@pytest.mark.skipif(c_compiler() is None, reason="no C compiler")
def test_code_that_does_not_compile_reports_rather_than_raises():
    r = execute(Snippet("c", "this is not c"))
    assert r.ok is False
    assert "compile failed" in (r.error or "")


def test_python_runs_too():
    r = execute(Snippet("python", "s = 'the quick brown fox'\nprint(s[5:])"))
    assert r.ok, r.error
    assert normalize_output(r.stdout) == "uick brown fox"


def test_an_endless_loop_is_killed_not_waited_on():
    r = execute(Snippet("python", "while True:\n    pass"))
    assert r.ok is False
    assert r.error == "timed out"


def test_a_crash_is_reported_not_raised():
    r = execute(Snippet("python", "raise SystemExit(3)"))
    assert r.ok is False
    assert "exit 3" in (r.error or "")


def test_normalization_forgives_the_trailing_newline_but_not_inner_spacing():
    assert outputs_match("hello", "hello\n")
    assert outputs_match("a\nb", "a  \nb\n")
    assert not outputs_match("a b", "a  b")


@pytest.mark.skipif(c_compiler() is None, reason="no C compiler")
def test_a_program_that_prints_nothing_is_not_ground_truth():
    """A real generation asked what a string-copy routine leaves in `dest`. The
    snippet had no printf at all, so it ran clean and printed "" — and treating
    that as the answer replaced the model's sensible "Hi\0" with nothing."""
    from manabi_server.processing.code_exec import printed_anything

    r = execute(Snippet("c", 'char d[8]; char *t = "Hi"; while ((*d++ = *t++));'))
    # Whether it compiles or not, an empty run must never count as verified.
    assert printed_anything(r) is False


def test_printed_anything_requires_visible_output():
    from manabi_server.processing.code_exec import printed_anything

    assert printed_anything(execute(Snippet("python", "x = 1"))) is False
    assert printed_anything(execute(Snippet("python", "print('')"))) is False
    assert printed_anything(execute(Snippet("python", "print('hi')"))) is True


# ── Real failures from the 2026-10-07 audit of 81 stored questions ──────────

from manabi_server.processing.code_exec import (  # noqa: E402
    check_code_question,
    converted_prompt,
    cpp_compiler,
    guess_lang,
    match_options,
)

needs_cc = pytest.mark.skipif(c_compiler() is None, reason="no C compiler")
needs_cxx = pytest.mark.skipif(cpp_compiler() is None, reason="no C++ compiler")


@needs_cc
def test_unsequenced_modification_is_undefined_not_an_answer():
    # q28: `y = --x + (x--)` was keyed "x=18, y=39, z=39"; gcc prints 38.
    r = execute(Snippet("c", 'int x = 20, y; y = --x + (x--); printf("%d %d\\n", x, y);'))
    assert r.ok is False
    assert r.undefined and "undefined" in r.undefined


@needs_cc
def test_reading_past_an_array_is_undefined():
    # q101: the loop reads arr[3]; -O0 and -O2 builds disagree (or gcc warns).
    src = "int arr[] = {1, 2, 3};\nint *p = arr;\nwhile (*p < 5) {\n printf(\"%d\", *p);\n p++;\n}"
    r = execute(Snippet("c", src))
    assert r.ok is False


@needs_cc
def test_a_single_printed_space_is_output():
    # q83: `ptrs[1][3]` of "Hello World" from +2 is ' ' — it was marked
    # "prints nothing" because whitespace was normalized away first.
    from manabi_server.processing.code_exec import printed_anything

    src = 'char *text = "Hello World";\nchar *p = text + 2;\nprintf("%c\\n", p[3]);'
    r = execute(Snippet("c", src))
    assert r.ok, r.error
    assert printed_anything(r)


def test_cpp_in_a_c_fence_is_compiled_as_cpp():
    s = extract_snippet('```c\n#include <iostream>\nint main(){ std::cout << 1; }\n```')
    assert s is not None and s.lang == "cpp"
    assert guess_lang('printf("%d", 3);') == "c"
    assert guess_lang("cout << x;") == "cpp"
    assert guess_lang("just prose") is None


@needs_cxx
def test_cpp_constructor_destructor_order_runs():
    src = """#include <iostream>
using namespace std;
class A { public: A(){ cout << "A"; } ~A(){ cout << "~A"; } };
class B : public A { public: B(){ cout << "B"; } ~B(){ cout << "~B"; } };
int main() { B b; return 0; }"""
    r = execute(Snippet("cpp", src))
    assert r.ok, r.error
    assert normalize_output(r.stdout) == "AB~B~A"


@needs_cxx
def test_output_that_depends_on_copy_elision_has_no_single_answer():
    # q108: keyed "Init Copy End\nEnd"; g++ elides the copy and prints "Init End".
    src = """#include <iostream>
using namespace std;
class Item {
public:
    Item() { cout << "Init "; }
    Item(const Item& i) { cout << "Copy "; }
    ~Item() { cout << "End" << endl; }
};
Item makeItem() { Item temp; return temp; }
int main() { Item x = makeItem(); return 0; }"""
    r = execute(Snippet("cpp", src))
    assert r.ok is False and r.undefined and "copy elision" in r.undefined


def test_sizeof_long_is_not_checked_on_a_machine_where_it_differs():
    r = execute(Snippet("c", 'printf("%zu", sizeof(long));'))
    assert r.ok is False and "platform" in (r.error or "")


def test_options_match_quoted_and_whitespace_variants():
    assert match_options(["`10 20`", "20 10", "10\n20"], "10 20\n") == [0]
    assert match_options(["1 2 3", "3 2 1"], "1\n2\n3\n") == [0]
    assert match_options(["'A'", "B"], "A") == [0]


MCQ_PROMPT = "What does this print?\n\n```c\nint a[] = {5, 10, 8};\nint *p = a;\nprintf(\"%d\\n\", *(p + 1));\n```"


@needs_cc
def test_a_wrong_mcq_key_is_corrected_to_the_printed_option():
    chk = check_code_question("mcq", MCQ_PROMPT, ["5", "10", "8", "6"], {"kind": "mcq", "correct_option": 0})
    assert chk.status == "corrected"
    assert chk.answer == {"kind": "mcq", "correct_option": 1, "verified": "executed"}


@needs_cc
def test_a_right_mcq_key_is_marked_verified():
    chk = check_code_question("mcq", MCQ_PROMPT, ["5", "10", "8", "6"], {"kind": "mcq", "correct_option": 1})
    assert chk.status == "agree" and chk.answer["verified"] == "executed"


@needs_cc
def test_an_mcq_with_no_matching_option_becomes_an_output_question():
    chk = check_code_question("mcq", MCQ_PROMPT, ["5", "11", "8", "6"], {"kind": "mcq", "correct_option": 1})
    assert chk.status == "converted" and chk.qtype == "output"
    assert chk.answer == {"kind": "output", "text": "10", "verified": "executed"}


@needs_cc
def test_a_wrong_short_output_key_is_corrected():
    chk = check_code_question("short", MCQ_PROMPT, None, {"kind": "short", "text": "5"})
    assert chk.status == "corrected" and chk.answer["text"] == "10"


@needs_cc
def test_a_value_question_that_does_not_ask_for_printed_output_is_left_alone():
    p = "What value does x hold at the end?\n\n```c\nint x = 3;\nx += 2;\nprintf(\"%d\", x * 0);\n```"
    assert check_code_question("short", p, None, {"kind": "short", "text": "5"}).status == "skip"


@needs_cc
def test_an_undefined_output_question_is_rejected():
    p = "What is printed?\n\n```c\nint i = 1;\nprintf(\"%d\\n\", i++ + i++);\n```"
    assert check_code_question("output", p, None, {"kind": "output", "text": "3"}).status == "rejected"


def test_converted_prompt_rewords_which_of_the_following():
    assert converted_prompt("Which of the following is the output of this code?").startswith(
        "What is the exact output"
    )



# ── A complete program that does not compile (live OOP topic test, 2026-10-07) ─

BROKEN = """What is the exact output of the program below?

```cpp
#include <iostream>
using namespace std;
class A {
public:
    void f() { cout << 1; }
};
void A::f() { cout << 2; }
int main() { A a; a.f(); return 0; }
```"""


@needs_cxx
def test_a_complete_program_that_does_not_compile_is_retired():
    chk = check_code_question("output", BROKEN, None, {"kind": "output", "text": "1"})
    assert chk.status == "rejected" and "does not compile" in chk.reason


@needs_cxx
def test_a_compile_error_key_is_right_when_the_program_does_not_compile():
    chk = check_code_question(
        "mcq", BROKEN.replace("exact output", "output"),
        ["1", "2", "12", "Compilation error"],
        {"kind": "mcq", "correct_option": 0},
    )
    assert chk.status == "corrected" and chk.answer["correct_option"] == 3


@needs_cxx
def test_a_cpp_program_that_forgot_iostream_still_runs():
    src = "int main() { cout << 7 << endl; return 0; }"
    r = execute(Snippet("cpp", src))
    assert r.ok, r.error
    assert normalize_output(r.stdout) == "7"


@needs_cc
def test_output_with_a_nul_character_is_retired():
    # printf("%c") of an empty stack's '\0' broke verification of a whole exam.
    p = "What is printed?\n\n```c\n#include <stdio.h>\nint main(void){ char c = 0; printf(\"x%cy\", c); return 0; }\n```"
    chk = check_code_question("output", p, None, {"kind": "output", "text": "xy"})
    assert chk.status == "rejected" and "non-printable" in chk.reason


VALUE_RESULT = """Assume the function `change` uses call by value-result (copy-in/copy-out) semantics. What is the exact output of the program below?

```c
#include <stdio.h>
int a = 5;
void change(int x) { x++; a = 10; x++; }
int main() { change(a); printf("%d\n", a); return 0; }
```"""


def test_assumed_non_c_semantics_are_not_settled_by_compiling():
    # gcc prints 10 (call by value); under value-result the answer is 7.
    chk = check_code_question("output", VALUE_RESULT, None, {"kind": "output", "text": "10"})
    assert chk.status == "unverifiable" and "semantics" in chk.reason


def test_a_reference_parameter_marks_cpp():
    s = extract_snippet("```c\nvoid f(int &v) { v++; }\nint main(){ int n=1; f(n); }\n```")
    assert s is not None and s.lang == "cpp"
    assert guess_lang("if (x & mask) { y(); }") != "cpp"


@needs_cc
def test_a_students_program_is_graded_by_running_both():
    from manabi_server.processing.code_exec import compare_programs

    ref = "```c\n#include <stdio.h>\nint main(void){ for (int i = 1; i <= 3; i++) printf(\"%d \", i * i); return 0; }\n```"
    good = "#include <stdio.h>\nint main(){ int i; for(i=1;i<4;i++){ printf(\"%d \", i*i); } return 0; }"
    bad = "#include <stdio.h>\nint main(){ printf(\"1 4 8\"); return 0; }"
    broken = "int main( { return 0 }"
    assert compare_programs(good, ref)["status"] == "passed"
    out = compare_programs(bad, ref)
    assert out["status"] == "failed" and out["expected_output"] == "1 4 9"
    err = compare_programs(broken, ref)
    assert err["status"] == "error" and "manabi-exec" not in err["message"]
