"""Text cleaning. Versioned: any rule change bumps SPEC_VERSION."""
from __future__ import annotations

import re

SPEC_VERSION = "0.2.0"

PLACEHOLDER_RUN = re.compile(r"_{2,}")
EMPTY_BRACKET = re.compile(r"[\(\[]\s*\[redacted\]\s*[\)\]]")
EXTRA_SPACE = re.compile(r"[ \t]{2,}")
BLANK_LINES = re.compile(r"\n{3,}")


def stripPlaceholders(text: str | None) -> str:
    """Collapse MIMIC's de-id underscores into one marker and tidy whitespace.

    Left in place, the underscore runs push the model toward imitating a blank
    form and stalling partway through.
    """
    if not text:
        return ""
    text = text.replace("\r\n", "\n")
    text = PLACEHOLDER_RUN.sub("[redacted]", text)
    text = EMPTY_BRACKET.sub("", text)
    text = EXTRA_SPACE.sub(" ", text)
    return BLANK_LINES.sub("\n\n", text).strip()


def clean_document(raw_note: str, doc_id: str) -> str:
    return stripPlaceholders(raw_note)
