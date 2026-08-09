"""Versioned prompts + JSON schemas for structured generation.

Grounding rules live in every prompt, but the real enforcement is layered
outside the prompt: schema-constrained decoding, source-id resolution against
the job's scope, and post-hoc support scoring.
"""

PROMPT_VERSION = "v3"

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
- If the sources do NOT cover the question: set grounded=false, START your
  answer by saying the module materials don't cover this, then — only if you
  are confident — answer briefly from general knowledge and set
  general_knowledge_used=true. Never silently blend the two.
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
