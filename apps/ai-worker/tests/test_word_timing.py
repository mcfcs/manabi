"""Word highlighting: recognised word times aligned to the displayed words."""

from manabi_ai.word_timing import align_starts


def test_heard_words_give_their_own_start_times():
    tokens = ["The", "term", "elite", "democracy", "caught", "on."]
    heard = [
        ("the", 0),
        ("term", 200),
        ("elite", 450),
        ("democracy", 800),
        ("caught", 1500),
        ("on", 1800),
    ]
    assert align_starts(tokens, heard, 2200) == [0, 200, 450, 800, 1500, 1800]


def test_an_unspoken_citation_is_passed_over_between_its_neighbours():
    tokens = ["Marcos", "fell", "(Thompson", "1995:12)", "in", "1986."]
    heard = [("marcos", 0), ("fell", 400), ("in", 900), ("1986", 1100)]
    starts = align_starts(tokens, heard, 2000)
    assert starts[0] == 0 and starts[1] == 400 and starts[4] == 900
    assert 400 <= starts[2] <= starts[3] <= 900  # interpolated, in order


def test_a_misheard_name_still_gets_a_time_and_nothing_goes_backwards():
    tokens = ["Quimpo", "argues", "that", "Akbayan", "won."]
    heard = [
        ("kim", 0),
        ("po", 150),
        ("argues", 400),
        ("that", 700),
        ("ack", 900),
        ("bayan", 1050),
        ("won", 1400),
    ]
    starts = align_starts(tokens, heard, 1800)
    assert starts == sorted(starts) and starts[1] == 400 and starts[2] == 700
    assert starts[-1] == 1400


def test_nothing_heard_spreads_the_words_over_the_clip():
    starts = align_starts(["one", "two", "three"], [], 3000)
    assert starts[0] == 0 and starts == sorted(starts) and starts[-1] < 3000
