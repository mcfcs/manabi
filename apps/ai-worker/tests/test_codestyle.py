"""The professor's style is measured from his files, not assumed."""

from manabi_ai import codestyle

PARAMPASS = """// demonstration of parameter passing in C/C++

#include <iostream>
using namespace std;

void change1(int& x)
{
   x = 15;
}

int main()
{
   int a;
   a = 5;
   change1(a);
   cout << a << endl;
   return 0;
}
"""

POINTERS = """#include <stdio.h>

int main()
{
   int *p;
   int i;
   int arr[3];
   for(i = 0; i < 3; i++)
   {
      arr[i] = i * 2;
   }
   p = arr;
   printf("%d\\n", *(p + 1));
   printf("%d\\n", arr[2]);
   return 0;
}
"""

TEACHER = """class teacher:public employee
{
   public:
      void promote();
};
"""

KR = """#include <stdio.h>

int main(void) {
    int a = 5;
    if (a > 3) {
        printf("%d\\n", a);
    }
    return 0;
}
"""


def test_the_professors_habits_are_measured():
    # Two of each: a habit needs at least two observations (one file proves nothing).
    s = codestyle.measure([PARAMPASS, PARAMPASS, POINTERS, POINTERS, TEACHER, TEACHER])
    assert s.indent == 3
    assert s.func_brace_own_line is True
    assert s.main == "int main()"
    assert s.declare_then_assign is True
    assert s.endl is True and s.using_std is True
    assert s.class_lowercase is True
    assert s.space_after_keyword is False


def test_a_different_style_is_measured_as_different():
    s = codestyle.measure([KR, KR])
    assert s.indent == 4
    assert s.func_brace_own_line is False
    assert s.main == "int main(void)"
    assert s.declare_then_assign is False


def test_the_style_block_names_the_rules_and_quotes_his_code():
    block = codestyle.style_block(
        [("parampass.cpp", PARAMPASS), ("pointers.c", POINTERS), ("teacher.h", TEACHER)]
    )
    assert "Indent with 3 spaces" in block
    assert "`int main()`" in block
    assert "his demos as the basis" in block
    assert "void change1(int& x)" in block  # a verbatim excerpt


def test_no_code_no_block():
    assert codestyle.style_block([]) == ""
    assert codestyle.style_block([("notes.txt", "just words")]) == ""
