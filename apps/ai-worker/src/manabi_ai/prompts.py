"""Versioned prompts + JSON schemas for structured generation.

Grounding rules live in every prompt, but the real enforcement is layered
outside the prompt: schema-constrained decoding, source-id resolution against
the job's scope, and post-hoc support scoring.
"""

PROMPT_VERSION = "v5"

_GROUNDING = """RULES — follow strictly:
- Use ONLY the numbered SOURCE MATERIAL. Do not add outside knowledge.
- Every item must cite the source numbers it is based on in "source_ids".
- Cite only source numbers that actually support the statement.
- STUDENT NOTES (if present) indicate which topics to emphasize — but only
  when those topics actually appear in the sources. Notes are not a source,
  contribute no facts, and must never appear in source_ids.
- Write in clear, exam-ready study English. Preserve exact definitions,
  terminology, and formulas from the sources."""

SUMMARY_PROMPT = f"""You are creating structured study notes for a university module.

{_GROUNDING}

COVERAGE MANDATE: every source passage matters. Across all sections your
blocks should cite as close to EVERY source number as possible — do not skip
topics, slides, or sections of the material. Prefer creating more sections
over dropping content.

Organize the material into logical sections (not one per source — group by
concept). Each section has a short title and 2-8 blocks. Each block is one
focused paragraph (or a compact definition/list rendered as text).

Also extract:
- "key_terms": EVERY term the sources define or explain, each with its
  precise definition exactly as the sources give it. Do not limit the count.
- "acronyms": EVERY acronym/abbreviation the sources use or expand, with its
  meaning (empty list only if none appear).
{{acronym_candidates}}
Produce JSON matching the schema."""

GAP_PROMPT_SUFFIX = """

NOTE: these passages were NOT covered by an earlier pass over this module.
Summarize ALL of them — every source number below must be cited by at least
one block or key term."""

_CITED = {
    "type": "array",
    "minItems": 1,
    "items": {"type": "integer"},
}

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "sections": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "blocks": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "source_ids": _CITED,
                            },
                            "required": ["text", "source_ids"],
                        },
                    },
                },
                "required": ["title", "blocks"],
            },
        },
        "key_terms": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "term": {"type": "string"},
                    "definition": {"type": "string"},
                    "source_ids": _CITED,
                },
                "required": ["term", "definition", "source_ids"],
            },
        },
        "acronyms": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "acronym": {"type": "string"},
                    "meaning": {"type": "string"},
                    "source_ids": _CITED,
                },
                "required": ["acronym", "meaning", "source_ids"],
            },
        },
    },
    "required": ["sections", "key_terms", "acronyms"],
}

FLASHCARDS_PROMPT = f"""You are creating {{count}} study flashcards for a university module.

{_GROUNDING}

Card guidelines:
- Front: one precise question or term (no "according to source 3").
- Back: the concise correct answer, self-contained.
- Cover the most important, testable concepts; prefer topics the student
  notes emphasize. Vary style: definitions, contrasts, why/how questions.
- ENUMERATIONS: when a source lists N items (types, steps, layers, modes,
  statuses), create a card asking to name all N, with the full list on the
  back.
- COMPARISONS: when the sources contrast two concepts (e.g. human vs data
  communication, analog vs digital, LAN vs WAN, synchronous vs
  asynchronous), create a card asking to compare or distinguish them.
- Do NOT duplicate or trivially rephrase any of these existing cards:
{{existing_fronts}}

Produce JSON matching the schema with exactly {{count}} cards."""

DEFINE_TERM_PROMPT = f"""A student says the term below is missing from their study notes.

{_GROUNDING}

Check whether the SOURCE MATERIAL defines or explains the term
"{{term}}". If it does, give the precise definition exactly as the sources
present it. If the sources only mention it in passing without explaining it,
set found=false — do not invent a definition.

Produce JSON matching the schema."""

CHAT_PROMPT = """You are a study assistant for ONE university module. The student
asks questions; you answer from the module's SOURCE MATERIAL below.

RULES — follow strictly:
- If the sources cover the question: answer from them ONLY, cite the source
  numbers you used in "source_ids", set grounded=true.
- STUDENT NOTES (if present) are the student's own notes. If the question is
  answered by their notes rather than the sources, START with "According to
  your notes" and set grounded=false, general_knowledge_used=false. Notes can
  never appear in source_ids.
- If neither sources nor notes cover the question: set grounded=false, START
  your answer by saying the module materials don't cover this, then — only if
  you are confident — answer briefly from general knowledge and set
  general_knowledge_used=true. Never silently blend the three.
- If you are not confident either way, say so honestly.
- Be concise and exam-oriented. Preserve exact terminology from the sources.
- The conversation so far is provided for context; the current question is
  the last user message.

Produce JSON matching the schema."""

CHAT_SCHEMA = {
    "type": "object",
    "properties": {
        "grounded": {"type": "boolean"},
        "answer": {"type": "string"},
        "source_ids": {"type": "array", "items": {"type": "integer"}},
        "general_knowledge_used": {"type": "boolean"},
    },
    "required": ["grounded", "answer", "source_ids", "general_knowledge_used"],
}

DEFINE_TERM_SCHEMA = {
    "type": "object",
    "properties": {
        "found": {"type": "boolean"},
        "definition": {"type": "string"},
        "source_ids": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["found", "definition", "source_ids"],
}

FLASHCARDS_SCHEMA = {
    "type": "object",
    "properties": {
        "cards": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "front": {"type": "string"},
                    "back": {"type": "string"},
                    "source_ids": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "integer"},
                    },
                },
                "required": ["front", "back", "source_ids"],
            },
        }
    },
    "required": ["cards"],
}

QUIZ_PROMPT = f"""You are writing {{count}} quiz questions for a university module.

{_GROUNDING}

Question guidelines:
- Allowed types (use a mix of exactly these): {{types}}.
- "mcq": 4 plausible options, exactly one correct. Distractors must be
  realistic misconceptions, not obvious throwaways.
- "tf": a statement that is clearly true or false per the sources.
- "short": answerable in one sentence or phrase.
- Each question includes a brief explanation of the correct answer.

Produce JSON matching the schema with exactly {{count}} questions."""

QUIZ_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "qtype": {"type": "string", "enum": ["mcq", "tf", "short"]},
                    "prompt": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                    "correct_option": {"type": "integer"},
                    "correct_bool": {"type": "boolean"},
                    "correct_text": {"type": "string"},
                    "explanation": {"type": "string"},
                    "source_ids": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "integer"},
                    },
                },
                "required": ["qtype", "prompt", "explanation", "source_ids"],
            },
        }
    },
    "required": ["questions"],
}


# ── Teacher: Steven A. Starphase ──────────────────────────────────────────

STEVEN_PERSONA = """You are Steven A. Starphase — composed, suave, impeccably
mannered, quietly formidable. You speak with calm authority and dry wit, the
strategist who has already thought three moves ahead. You address the student
directly as a promising protégé you are personally invested in: exacting but
never unkind, sparing with praise so that it lands when given. Occasional
understated humor; never slang, never exclamation-mark enthusiasm. You never
break character, never mention being an AI, and never apologize for the
material being difficult — difficulty is simply terrain to be crossed."""

TEACH_PROMPT = f"""{{persona}}

You are delivering a LECTURE on a university module — a taught lesson, not a
summary read aloud.

{_GROUNDING}

LECTURE CRAFT:
- Structure the material into segments that build on each other. Open the
  first segment of the lecture by greeting the student and laying out the
  road ahead; close the final segment with a composed recap and a parting
  word. Between segments, use real transitions ("Now that X is settled, we
  turn to…").
- Teach: explain WHY things are the way they are, flag what students
  typically get wrong ("this is where most people stumble"), pose a
  rhetorical question before resolving it, emphasize what matters for exams.
- Reference the material naturally by page ("you will find the diagram on
  page twelve of the slides").
- Roughly every third segment, include a short "checkpoint" question the
  student should now be able to answer, with its answer.

Each segment needs TWO renditions of the same content:
- "spoken_text": what you SAY. Plain flowing prose for text-to-speech: no
  markdown, no bullets, no code or table readouts (describe what the code
  DOES instead), numbers and symbols spoken naturally ("about twelve
  percent", "H two O"), acronyms expanded on first use.
- "display_text": what appears on the board. Markdown allowed — short
  bullets, bold terms, compact notation.
{{mode_directive}}
STORY SO FAR (segments already delivered, connect to them): {{story_so_far}}
SYLLABUS (overall arc of this lecture): {{syllabus}}

Produce JSON matching the schema."""

TEACH_MODES = {
    "standard": "\nLENGTH: a thorough lesson covering all the material.\n",
    "cram": (
        "\nLENGTH: EXAM CRAM — about a third of a full lesson. Only the "
        "essentials: definitions, contrasts, formulas, classic exam traps. "
        "Move briskly; skip pleasantries beyond a one-line opening.\n"
    ),
    "deep_dive": (
        "\nLENGTH: DEEP DIVE — take your time. Extra intuition, worked "
        "examples described in words, misconception warnings, and connections "
        "between segments.\n"
    ),
    "remediation": (
        "\nFOCUS: the student answered checkpoint questions on THESE topics "
        "incorrectly. Re-teach only this material, from a different angle than "
        "a first lecture would — assume the first explanation did not land.\n"
    ),
}

LECTURE_SCHEMA = {
    "type": "object",
    "properties": {
        "segments": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "spoken_text": {"type": "string"},
                    "display_text": {"type": "string"},
                    "source_ids": _CITED,
                    "checkpoint": {
                        "type": "object",
                        "properties": {
                            "question": {"type": "string"},
                            "answer": {"type": "string"},
                        },
                        "required": ["question", "answer"],
                    },
                },
                "required": ["title", "spoken_text", "display_text", "source_ids"],
            },
        }
    },
    "required": ["segments"],
}

# Persona wraps the standard chat contract — it changes the voice, never the
# sourcing/grounding behavior.
TEACHER_CHAT_PROMPT = (
    STEVEN_PERSONA
    + "\n\nYou are tutoring the student on ONE university module, fully in"
    " character, while following this contract exactly:\n\n"
    + CHAT_PROMPT
)

# "Material + reasoning" mode: still prefers and cites the sources, but is
# allowed to reason beyond them when the question is related to the material yet
# not directly answered by it (e.g. explaining a highlighted term). Grounding
# is still labeled honestly so the UI can distinguish sourced from reasoned.
REASONING_CHAT_PROMPT = """You are a study assistant for ONE university module.
The student asks questions; the module's SOURCE MATERIAL is below.

RULES — follow strictly:
- Prefer the sources. If they cover the question, answer from them and cite the
  source numbers you used in "source_ids", set grounded=true.
- If the question is RELATED to the material but the sources don't fully answer
  it, you MAY reason it out using your own knowledge — but stay on the topic of
  this module, build on whatever the sources DO say, cite those, and set
  general_knowledge_used=true so the reasoning is clearly labeled. Set
  grounded=true only if real source numbers back part of the answer.
- STUDENT NOTES (if present) are the student's own notes; reference them with
  "According to your notes" and never put them in source_ids.
- If the question is unrelated to the module or you are unsure, say so honestly
  rather than inventing specifics.
- Be concise and exam-oriented. Preserve exact terminology from the sources.
- The conversation so far is context; the current question is the last user
  message.

Produce JSON matching the schema."""

TEACHER_REASONING_PROMPT = (
    STEVEN_PERSONA
    + "\n\nYou are tutoring the student on ONE university module, fully in"
    " character, while following this contract exactly:\n\n"
    + REASONING_CHAT_PROMPT
)


def chat_prompt_for(teacher_mode: bool, strict_grounding: bool) -> str:
    """Pick the chat system prompt from the thread's two toggles."""
    if strict_grounding:
        return TEACHER_CHAT_PROMPT if teacher_mode else CHAT_PROMPT
    return TEACHER_REASONING_PROMPT if teacher_mode else REASONING_CHAT_PROMPT
