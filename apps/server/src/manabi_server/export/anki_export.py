"""Flashcards → Anki .apkg via genanki.

Stable IDs everywhere: model/deck ids derive from names, note GUIDs derive
from Manabi card ids — so re-importing an updated export updates existing
cards in Anki instead of duplicating them.
"""

import hashlib
import tempfile
from pathlib import Path

import genanki


def _stable_id(name: str) -> int:
    return int(hashlib.sha256(name.encode()).hexdigest()[:8], 16)


_MODEL = genanki.Model(
    _stable_id("manabi-basic-v1"),
    "Manabi Basic",
    fields=[{"name": "Front"}, {"name": "Back"}, {"name": "Source"}],
    templates=[
        {
            "name": "Card 1",
            "qfmt": "{{Front}}",
            "afmt": (
                '{{FrontSide}}<hr id="answer">{{Back}}'
                '<div style="margin-top:14px;font-size:12px;color:#28518F;">'
                "{{Source}}</div>"
            ),
        }
    ],
    css=(
        ".card { font-family: Georgia, serif; font-size: 19px; text-align: center;"
        " color: #1C2434; background-color: #FAF7F1; }"
    ),
)


class _ManabiNote(genanki.Note):
    def __init__(self, manabi_card_id: int, **kwargs):
        super().__init__(**kwargs)
        self._manabi_guid = genanki.guid_for("manabi-card", manabi_card_id)

    @property
    def guid(self):
        return self._manabi_guid


def build_apkg(deck_name: str, cards: list[tuple[int, str, str, str]]) -> bytes:
    """cards: (manabi_card_id, front, back, source_label)"""
    deck = genanki.Deck(_stable_id(f"manabi-deck:{deck_name}"), deck_name)
    for card_id, front, back, source in cards:
        deck.add_note(
            _ManabiNote(
                manabi_card_id=card_id,
                model=_MODEL,
                fields=[front, back, source],
            )
        )
    with tempfile.TemporaryDirectory(prefix="manabi_apkg_") as tmp:
        path = Path(tmp) / "deck.apkg"
        genanki.Package(deck).write_to_file(str(path))
        return path.read_bytes()
