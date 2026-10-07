

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
