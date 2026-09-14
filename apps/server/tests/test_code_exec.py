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
