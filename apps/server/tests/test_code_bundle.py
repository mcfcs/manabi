"""Code materials keep the professor's code exactly — indentation included."""

import io
import zipfile

from manabi_server.processing import code_bundle

TEACHER_H = (
    '#include "employee.h"\n\nclass teacher:public employee\n'
    "{\n   public:\n      void promote();\n};\n"
)
MAIN = "int main()\n{\n   employee *e2;\n   e2 = new teacher();\n   e2->promote();\n}\n"


def test_a_bundle_round_trips_every_file_byte_for_byte():
    text = code_bundle.make_bundle([("teacher.h", TEACHER_H), ("methoddemo.cpp", MAIN)])
    assert code_bundle.parse_bundle(text) == [("teacher.h", TEACHER_H), ("methoddemo.cpp", MAIN)]
    assert "      void promote();" in text  # 6-space member indent survives


def test_plain_text_is_not_a_bundle():
    assert code_bundle.parse_bundle("Some notes\n//// FILE: x.c\n") is None


def test_trailing_spaces_and_crlf_are_cleaned_but_indentation_is_not():
    assert code_bundle.clean_code("int main()\r\n{\r\n   int a;   \r\n}\r\n") == (
        "int main()\n{\n   int a;\n}\n"
    )


def test_zip_sources_are_extracted_and_junk_skipped():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("polymorphism/teacher.h", TEACHER_H)
        z.writestr("polymorphism/methoddemo.cpp", MAIN)
        z.writestr("__MACOSX/polymorphism/._teacher.h", b"\x00\x05junk")
        z.writestr("polymorphism/Makefile", "all:\n\tg++ *.cpp\n")
        z.writestr("polymorphism/a.out", b"\x7fELF\x00\x00")
    names = [n for n, _ in code_bundle.files_from_zip(buf.getvalue())]
    assert names == ["methoddemo.cpp", "teacher.h"]


def test_headers_come_first_and_main_last():
    files = [
        ("methoddemo.cpp", MAIN),
        ("teacher.cpp", "void teacher::promote() {}\n"),
        ("teacher.h", TEACHER_H),
    ]
    assert [n for n, _ in code_bundle.order_files(files)] == [
        "teacher.h",
        "teacher.cpp",
        "methoddemo.cpp",
    ]
