"""Code-output flashcards: the program's real output wins over the model's
back, and a card whose code cannot be run is removed."""

from types import SimpleNamespace

import pytest
from manabi_server.jobs import tasks
from manabi_server.processing.code_exec import c_compiler


class _Session:
    def __init__(self, cards):
        self.cards = cards
        self.deleted = []
        self.statements = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, stmt):
        self.statements += 1
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: list(self.cards)))

    def delete(self, obj):
        self.deleted.append(obj)

    def commit(self):
        pass


def _card(ord_, front, back, edited=False):
    return SimpleNamespace(id=ord_, ord=ord_, front=front, back=back, edited=edited)


@pytest.mark.skipif(c_compiler() is None, reason="no C compiler")
def test_the_run_corrects_a_wrong_back_and_removes_unrunnable_cards(monkeypatch):
    right = _card(0, 'What does this print?\n\n```c\nint x = 3;\nprintf("%d", x * 2);\n```', "6")
    wrong = _card(1, 'What does this print?\n\n```c\nint x = 3;\nprintf("%d", x++ + 1);\n```', "5")
    broken = _card(
        2, "What does this print?\n\n```c\nint main(void) { return undefined_name; }\n```", "0"
    )
    plain = _card(3, "Static binding happens when?", "compile time")
    session = _Session([right, wrong, broken, plain])
    monkeypatch.setattr(tasks, "db_session", lambda: session)

    counts = tasks.verify_card_outputs.func(artifact_id=1)

    assert counts == {"agree": 1, "corrected": 1, "removed": 1}
    assert wrong.back == "4"
    assert session.deleted == [broken]
    assert plain.back == "compile time"
