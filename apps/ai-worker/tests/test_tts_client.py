

def test_tiny_sentences_are_spoken_with_a_neighbour():
    # "Welcome back." alone came back silent from the v2ProPlus voice.
    from manabi_ai.tts_client import merge_tiny_groups

    assert merge_tiny_groups(["Welcome back.", "We have traversed C."]) == [
        "Welcome back. We have traversed C."
    ]
    assert merge_tiny_groups(["A long enough sentence here.", "Thanks."]) == [
        "A long enough sentence here. Thanks."
    ]
    assert merge_tiny_groups(["One two three four five."]) == ["One two three four five."]
    assert merge_tiny_groups(["Hi."]) == ["Hi."]


def test_questions_and_exclamations_pick_their_delivery():
    from manabi_ai.tts_client import mood_for

    assert mood_for("So why did it fail?") == "question"
    assert mood_for('He asked, "why?"') == "question"
    assert mood_for("Stop right there!") == "emphatic"
    assert mood_for("It failed.", default="warm") == "warm"


def test_a_mood_without_a_clip_falls_back_to_the_calm_reference(monkeypatch):
    from types import SimpleNamespace

    from manabi_ai import tts_client

    settings = SimpleNamespace(
        tts_ref_audio="calm.wav",
        tts_ref_text="Calm.",
        tts_ref_bank={"question": ("q.wav", "Really?")},
    )
    monkeypatch.setattr(tts_client, "get_settings", lambda: settings)
    assert tts_client.reference("question") == ("q.wav", "Really?")
    assert tts_client.reference("warm") == ("calm.wav", "Calm.")


def test_a_broken_reference_bank_is_ignored():
    from manabi_ai.config import WorkerSettings

    assert WorkerSettings(tts_refs="{not json").tts_ref_bank == {}
    bank = WorkerSettings(
        tts_refs='{"question": {"path": "q.wav", "text": "Really?"}, "warm": {"path": ""}}'
    ).tts_ref_bank
    assert bank == {"question": ("q.wav", "Really?")}
