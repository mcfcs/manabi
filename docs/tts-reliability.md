# Missing speech and long pauses: 2026-09-24 investigation

The Article VI and VII TXT sources and stored `spoken_text` were intact.
Words were missing from the **saved MP3s**, so the player and document parser
were not the cause of those omissions.

Local Whisper transcription and FFmpeg silence detection found, for example:

- Article VII, Section 1: the old 2.88-second clip contained only “Section one”
  and about 2.03 seconds of silence. The full executive-power sentence was
  present in the script.
- Article VI, Section 3: about 7.59 seconds of the old 10.68-second clip was
  silence. Most of the Senator-qualification clauses were absent.

## Cause and changes

Manabi split each paragraph before calling GPT-SoVITS, but left the server's
`text_split_method` at its default, `cut5`. That splits again at punctuation,
including commas. Comparing the same text and seed showed a missing clause
with `cut5` restored with `cut0`. The same seed produced equivalent speech
with parallel inference on or off; changing that mode was not necessary.
The upstream [API](https://github.com/RVC-Boss/GPT-SoVITS/blob/main/api_v2.py)
and [splitter](https://github.com/RVC-Boss/GPT-SoVITS/blob/main/GPT_SoVITS/TTS_infer_pack/text_segmentation_method.py)
define these settings.

The client now owns segmentation (up to 200 characters, preferring clause
boundaries), keeps section labels and abbreviations together, and requests
`cut0` with no additional server-inserted fragment silence. It preserves the
existing trained weights, reference recording, speed, and sampler defaults.
Numbered uppercase labels such as `SECTION 22` are cased as `Section 22`
before synthesis. Both small and large-v3 Whisper transcriptions confirmed
that the uppercase label was being spelled out; real acronyms remain intact.

Previously any response over 1,000 bytes passed. Silence easily exceeds that
size. Now each WAV is decoded and checked for truncation, measurable speech,
implausibly little speech for its input, and long internal silent gaps. Failed
takes retry with fresh sampling; persistently bad sentences get one bounded
attempt as shorter clauses. If those fail too, synthesis fails visibly instead
of publishing incomplete audio. Only leading/trailing silence is trimmed,
with margins for quiet consonants and breathing; internal gaps are not erased
to conceal an omitted clause. Player paragraph pauses were also shortened.

These are acoustic sanity checks, **not a guarantee of word-perfect speech**.
They catch silent takes and gross early stops; a fluent substitution or a small
omission can still pass. ASR is useful for auditing passages but also makes
recognition mistakes, especially with legal names and pronunciation.

## Verification and existing audio

Six targeted saved passages were re-synthesized and transcribed locally. The
Section 1 sentence returned; Section 3's measured silence fell below one
second, with the missing clauses restored. A newly generated silent take was
rejected and recovered automatically. This was a targeted regression check,
not a population-wide word-error benchmark.

Existing recordings stay cached until replaced. The narration bar's
**Re-record this reading** control uses the existing force-prepare endpoint
to create new segment IDs, so browsers do not replay immutable cached MP3s.
It is disabled while a recording is in progress or the voice is unavailable.
The user's Article VI and VII recordings were backed up under the ignored
`storage/tts-audit/` directory before regeneration. Other saved readings can be
re-recorded using the same control.
