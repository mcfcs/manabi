"""The stdin/stdout judge: expectations come from running the reference."""

import pytest
from manabi_server.processing.code_exec import c_compiler, cpp_compiler
from manabi_server.processing.judge import expected_outputs, judge

SUM_C = """#include <stdio.h>

int main()
{
   int n, i, x, total;
   scanf("%d", &n);
   total = 0;
   for(i = 0; i < n; i++)
   {
      scanf("%d", &x);
      total = total + x;
   }
   printf("%d\\n", total);
   return 0;
}
"""

STACK_CPP = """#include <iostream>
using namespace std;

int main()
{
   int n, x, top;
   int s[100];
   top = 0;
   cin >> n;
   while(n-- > 0)
   {
      cin >> x;
      s[top++] = x;
   }
   while(top > 0)
      cout << s[--top] << " ";
   cout << endl;
   return 0;
}
"""

needs_c = pytest.mark.skipif(c_compiler() is None, reason="no C compiler")
needs_cpp = pytest.mark.skipif(cpp_compiler() is None, reason="no C++ compiler")


@needs_c
def test_expected_outputs_come_from_running_the_reference():
    exp = expected_outputs("c", SUM_C, ["3\n1 2 3\n", "1\n10\n", "4\n-1 1 -1 1\n", "2\n5 5\n"])
    assert exp.ok, exp.problem
    assert [t["output"] for t in exp.tests] == ["6\n", "10\n", "0\n", "10\n"]


@needs_c
def test_a_correct_solution_is_accepted_and_a_wrong_one_is_not():
    tests = expected_outputs("c", SUM_C, ["3\n1 2 3\n", "2\n4 4\n", "1\n7\n"]).tests
    assert judge("c", SUM_C, tests).verdict == "accepted"
    off_by_one = SUM_C.replace("i < n", "i < n - 1")
    j = judge("c", off_by_one, tests)
    assert j.verdict == "wrong" and j.passed < j.total
    first_wrong = next(r for r in j.results if r.verdict == "wrong")
    assert first_wrong.expected and first_wrong.got  # shown side by side


@needs_c
def test_compile_errors_and_infinite_loops_are_reported():
    assert judge("c", "int main() { return x; }", [{"input": "", "output": "1"}]).verdict == (
        "compile_error"
    )
    loop = "int main()\n{\n   while(1) { }\n}\n"
    assert judge("c", loop, [{"input": "", "output": "1"}], limit_ms=500).verdict == "time_limit"


@needs_cpp
def test_a_stack_homework_in_cpp():
    exp = expected_outputs("cpp", STACK_CPP, ["3\n1 2 3\n", "1\n9\n", "4\n4 3 2 1\n", "2\n7 8\n"])
    assert exp.ok, exp.problem
    assert exp.tests[0]["output"] == "3 2 1\n"
    assert judge("cpp", STACK_CPP, exp.tests).verdict == "accepted"


def test_python_runs_too():
    code = "n = int(input())\nprint(n * n)\n"
    exp = expected_outputs("python", code, ["3\n", "4\n", "0\n", "12\n"])
    assert exp.ok and exp.tests[1]["output"] == "16\n"


@needs_c
def test_a_reference_that_prints_a_constant_is_rejected():
    const = '#include <stdio.h>\nint main()\n{\n   printf("42\\n");\n   return 0;\n}\n'
    assert not expected_outputs("c", const, ["1\n", "2\n", "3\n", "4\n"]).ok
