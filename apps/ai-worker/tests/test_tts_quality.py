"""A big WAV is not evidence that the model spoke the requested sentence."""

import array
import io
import math
import wave
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from manabi_ai import tts_client as tts


def wav(*parts: tuple[float, int]) -> bytes:
    rate = 16000
    samples = array.array("h")
    for seconds, amplitude in parts:
        samples.extend(
            int(amplitude * math.sin(2 * math.pi * 220 * i / rate))
            for i in range(int(rate * seconds))
        )
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        w.writeframes(samples.tobytes())
    return out.getvalue()


def seconds(data: bytes) -> float:
    with wave.open(io.BytesIO(data), "rb") as w:
        return w.getnframes() / w.getframerate()


@pytest.mark.parametrize(
    "audio",
    [wav((3, 0)), wav((3, 10)), b"not a WAV"],
    ids=["silence", "noise-floor", "bad-container"],
)
def test_rejects_silence_even_when_the_response_is_large(audio):
    with pytest.raises(tts.TTSQualityError):
        tts._validate_and_trim_wav(audio, "The executive power shall be vested in the President.")


def test_rejects_short_speech_padded_with_silence():
    audio = wav((0.3, 6000), (8, 0))
    with pytest.raises(tts.TTSQualityError, match="stopped early"):
        tts._validate_and_trim_wav(
            audio, "A long sentence containing many words must not end here."
        )


def test_rejects_internal_gaps_instead_of_hiding_missing_words():
    with pytest.raises(tts.TTSQualityError, match="silent gap"):
        tts._validate_and_trim_wav(
            wav((1, 6000), (2, 0), (1, 6000)), "A sentence with a missing clause."
        )


def test_trims_edges_without_cutting_speech_or_internal_pauses():
    cleaned = tts._validate_and_trim_wav(
        wav((1, 0), (1, 6000), (0.4, 0), (1, 6000), (2, 0)), "An ordinary sentence with a pause."
    )
    assert seconds(cleaned) == pytest.approx(2.68, abs=0.02)


def test_rejects_truncated_wav():
    with pytest.raises(tts.TTSQualityError, match="truncated"):
        tts._validate_and_trim_wav(wav((1, 6000))[:-100], "A sentence.")


def test_fast_speech_is_allowed_at_the_requested_speed():
    assert tts._validate_and_trim_wav(
        wav((0.5, 6000)), "One two three four five six seven eight.", speed=2
    )


@pytest.mark.asyncio
async def test_silent_take_is_retried_with_engine_splitting_disabled(monkeypatch):
    monkeypatch.setattr(
        tts,
        "get_settings",
        lambda: SimpleNamespace(
            tts_url="http://voice",
            tts_ref_audio="ref.wav",
            tts_ref_text="Reference.",
            tts_speed=1,
        ),
    )
    requests = []

    def reply(request):
        requests.append(request)
        return httpx.Response(200, content=wav((2, 0)) if len(requests) == 1 else wav((2, 6000)))

    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        audio = await tts._request_wav(client, "This sentence must be spoken in full.")
    assert seconds(audio) == pytest.approx(2)
    assert len(requests) == 2
    assert all(r.url.params["text_split_method"] == "cut0" for r in requests)
    assert all(r.url.params["fragment_interval"] == "0" for r in requests)


@pytest.mark.asyncio
async def test_all_bad_takes_fail_instead_of_returning_the_longest(monkeypatch):
    monkeypatch.setattr(
        tts,
        "get_settings",
        lambda: SimpleNamespace(
            tts_url="http://voice",
            tts_ref_audio="ref.wav",
            tts_ref_text="Reference.",
            tts_speed=1,
        ),
    )
    attempts = []

    def reply(request):
        attempts.append(request)
        return httpx.Response(200, content=wav((len(attempts), 0)))

    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        with pytest.raises(tts.TTSQualityError):
            await tts._request_wav(client, "This must be spoken.")
    assert len(attempts) == 3


@pytest.mark.asyncio
async def test_shorter_fallback_must_preserve_and_synthesize_every_word(monkeypatch):
    source = "This is an unusually difficult sentence, but every word must still be spoken."
    request = AsyncMock(side_effect=[tts.TTSQualityError("short"), b"first", b"second"])
    monkeypatch.setattr(tts, "_request_wav", request)
    assert await tts._fragment_wavs(None, source) == [b"first", b"second"]
    parts = [c.args[1] for c in request.await_args_list[1:]]
    assert " ".join(parts) == source
