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

The full-document audit also found fluent omissions (for example, "or a
Vice-President") and an unintelligible tail that passed the acoustic checks.
Document narration now additionally transcribes each fragment with local
CPU/int8 Whisper before accepting it. Substantial missing phrases or very
low text coverage trigger the same retry/shorter-clause path. It never primes
recognition with the requested text. The check is enabled by default through
`TTS_VERIFY_SPEECH`; `TTS_VERIFICATION_MODEL` defaults to `small` and can point
to a local model directory. A named model downloads once if it is not cached.
Spoken chat and voice previews keep the faster acoustic-only path.

These are conservative checks, **not a guarantee of word-perfect speech**.
ASR also makes recognition mistakes, especially with uncommon legal terms.
The comparison tolerates small substitutions and ignores number formatting;
it does not verify numeric accuracy or tiny headings. This trades additional
CPU time and occasional retries for fewer incomplete saved readings. Failed
recognition/model loading fails the job visibly rather than bypassing checks.
Shorter retries also avoid stranding tiny endings such as "by law.", which
repeatedly produced silence during the full audit.

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

The completed full run replaced all **105 paragraphs** (about 5,550 words):
Article VI is 56/56 ready and Article VII is 49/49 ready. The four passages
flagged during the first pass were replaced with new segment IDs using the
text-verified path, and the final four unfinished paragraphs completed with
the same checks. Source and stored script text were preserved. The final
whole-paragraph audit has no remaining flags under the conservative
completeness criteria above; this is not a claim of zero word errors.

With FFmpeg silence detection at -40 dB and a 350 ms minimum gap, measured
silence across the 105 MP3s fell from **487.8 to 72.6 seconds**. Paragraphs
containing a silent gap longer than two seconds fell from **36 to zero**.
These measurements include ordinary pauses as well as unwanted silence,
and exclude the player's separate paragraph delay. Final duration is about
15:30 for Article VI and 13:23 for Article VII. Both API statuses are `ready`,
with no active jobs or errors; replacement audio URLs were checked via HTTP.

Validation: 396 backend/worker tests and 37 frontend tests passed, along with
the production web build, TypeScript checks, and targeted Python lint checks.
The re-record control was exercised in the browser with its request
intercepted to verify `force: true`; actual regeneration used the live API.
