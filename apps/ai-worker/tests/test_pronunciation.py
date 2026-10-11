"""Pronunciation list: the fixed rules, respelling application, and choosing
the respelling whose real sounds are closest to the intended ones."""

from types import SimpleNamespace

import pytest
from manabi_ai import pronunciation
from manabi_core import pronounce
from manabi_core.pronounce import Entry, apply, letters, needs_respelling, phone_distance


def test_symbols_the_voice_drops_are_spoken():
    assert apply("We write C++ and C# code.", []) == "We write C plus plus and C sharp code."
    assert apply("p->next == NULL", []) == "p arrow next equals equals NULL"


def test_plural_acronyms_are_read_as_letters():
    # "NGOs" was read as a word, "en-goes"; a possessive s is said as "z".
    assert apply("POs and NGOs work together.", []) == "P O's and N G O's work together."
    assert letters("PDSP") == "P D S P"


def test_respellings_replace_whole_words_and_keep_possessives():
    entries = [Entry("Quimpo", "Keem Poe"), Entry("trapo", "trah Poe")]
    assert apply("Quimpo's view of trapos and the Trapo.", entries) == (
        "Keem Poe's view of trapos and the trah Poe."
    )  # "trapos" is a different word: untouched


def test_an_all_caps_term_matches_only_itself():
    entries = [Entry("EDSA", "Ed sah")]
    assert apply("EDSA and Edsa", entries) == "Ed sah and Edsa"


def test_longest_term_wins():
    entries = [Entry("utang", "oo tong"), Entry("utang na loob", "oo tong nah low ob")]
    assert apply("utang na loob matters", entries) == "oo tong nah low ob matters"


def test_keep_entries_change_nothing():
    assert apply("Marcos fell.", [Entry("Marcos", "Marcos")]) == "Marcos fell."


def test_only_unknown_words_need_a_respelling():
    assert needs_respelling("Quimpo", known=False)
    assert needs_respelling("Huk", known=False)  # would be spelled H-U-K
    assert not needs_respelling("Marcos", known=True)
    assert not needs_respelling("CPP", known=False)  # short initialism: already spelled
    assert not needs_respelling("NGOs", known=False)  # the fixed rule handles it


def test_words_strip_possessives_and_dedupe():
    assert pronounce.words("Quimpo's book. Quimpo agrees, Huk.") == [
        "Quimpo",
        "book",
        "agrees",
        "Huk",
    ]


def test_phone_distance_ignores_stress():
    assert phone_distance(["K", "IY1", "M"], ["K", "IY0", "M"]) == 0
    assert phone_distance(["K", "IY1"], ["P", "OW1"]) == 1


def test_pick_keeps_the_candidate_closest_to_the_intended_sounds():
    sounds = {
        "Keem poh": {"phones": ["K", "IY1", "M", "P", "OW1"]},
        "Kimpo": {"phones": ["K", "IH1", "M", "P", "OW0"]},
        "Keempoh": {"phones": ["K", "IY1", "EH1", "M", "P", "IY1", "OW1"]},
    }
    say, match = pronunciation.pick("K IY1 M P OW0", ["Keempoh", "Kimpo", "Keem poh"], sounds)
    assert say == "Keem poh" and match == 1.0


def test_pick_without_a_probe_takes_the_first_candidate():
    assert pronunciation.pick("K IY1 M", ["Keem", "Kim"], {}) == ("Keem", None)


class _DB:
    def __init__(self):
        self.inserted = []

    async def execute(self, stmt):
        params = stmt.compile().params
        self.inserted.append(params)
        return SimpleNamespace(all=lambda: [])

    async def commit(self):
        pass


@pytest.mark.asyncio
async def test_learn_asks_only_about_unknown_words(monkeypatch):
    course = SimpleNamespace(id=4, code="SocSc 14", name="Politics")
    asked = []

    async def entries(db, course_id):
        return [Entry("Kerkvliet", "Kerk vleet")]

    async def probe(texts):
        known = {"the", "argues", "and", "rebellion", "Marcos"}
        phones = {"Keem Poe": ["K", "IY1", "M", "P", "OW1"], "Hook": ["HH", "UH1", "K"]}
        return {t: {"known": t in known, "phones": phones.get(t, ["X"])} for t in texts}

    async def generate(system, user, schema, **kw):
        asked.append(user)
        return {
            "terms": [
                {
                    "term": "Quimpo",
                    "kind": "word",
                    "arpabet": "K IY1 M P OW0",
                    "candidates": ["Keem-Poe", "Kimpo"],
                },
                {"term": "Huk", "kind": "word", "arpabet": "HH UH1 K", "candidates": ["Hook"]},
            ]
        }

    monkeypatch.setattr(pronunciation, "course_entries", entries)
    monkeypatch.setattr(pronunciation.g2p, "probe", probe)
    monkeypatch.setattr(pronunciation, "generate_structured", generate)
    db = _DB()
    added = await pronunciation.learn(
        db, course, ["Quimpo argues the Huk rebellion and Marcos.", "Kerkvliet and Quimpo."]
    )
    assert added == 2
    assert "TERM: Quimpo" in asked[0] and "TERM: Huk" in asked[0]
    assert "TERM: Kerkvliet" not in asked[0] and "TERM: Marcos" not in asked[0]
    values = db.inserted[-1]
    says = sorted(v for k, v in values.items() if k.startswith("say"))
    assert says == ["Hook", "Keem Poe"]  # the hyphen was turned into a space
