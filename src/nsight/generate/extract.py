"""Sort the doctor's own patient instructions into the four patient sections.

The model does not rewrite what the doctor already wrote for the patient. Each
sentence keeps the doctor's wording and lands in the section it belongs to, by
simple rules. Only the guarded plain-language pass may reword it afterwards.
"""
from __future__ import annotations

import re

from nsight.evaluate.metrics import BOILERPLATE, SENTENCE_END
from nsight.generate.prompts import SECTION_HEADERS
from nsight.ingest.segmentation import NEXT_HEADER

HAPPENED, TODO, HELP, FOLLOWUP = SECTION_HEADERS

BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
HELP_WORDS = re.compile(
    r"emergenc|\bE[RD]\b|911|right away|immediately|come back|return to|go to the hospital|"
    r"seek (medical )?(care|attention)", re.IGNORECASE)
CALL_IF = re.compile(r"\bcall\b.{0,80}\bif\b|\bif\b.{0,120}\bcall\b", re.IGNORECASE)
FOLLOW_WORDS = re.compile(
    r"appointment|follow[- ]?up|will call you|to schedule|schedule (an?|your)|\bsee (dr|your|the)\b|"
    r"clinic visit|referr", re.IGNORECASE)
HAPPENED_WORDS = re.compile(
    r"\b(you were|you came|you had|you have been|we found|we gave|we treated|we removed|we did|"
    r"we placed|we closed|we think|was caused|were caused|you lost|you received|you got)\b",
    re.IGNORECASE)
TODO_START = re.compile(
    r"^(please |you (will )?need|you should|you must|you can|take|use|do not|don't|never|keep|check|"
    r"weigh|eat|drink|avoid|stop|start|continue|get|make sure|bring|limit|a visiting nurse|your nurse|"
    r"if your)", re.IGNORECASE)

FILLER = re.compile(
    r"^(please )?(see|refer to|review) (the )?(details|instructions|information|below|above|attached)|"
    r"\b(as|see) (detailed |listed )?(below|above)\.?$|^\(?see below\)?\.?$", re.IGNORECASE)

# fewer units than this and the doctor said too little to build a document from
MIN_UNITS = 3


def units(text: str) -> list[list[str]]:
    """Paragraphs of units. A bullet stays whole; a prose paragraph splits into sentences.

    MIMIC wraps lines at about 80 characters, so a line that does not start a bullet
    continues the one before it.
    """
    paragraphs = []
    for block in re.split(r"\n\s*\n", text or ""):
        items: list[tuple[str, bool]] = []
        for line in (l.strip() for l in block.splitlines()):
            if not line:
                continue
            if BULLET.match(line) or not items:
                items.append((BULLET.sub("", line), bool(BULLET.match(line))))
            else:
                items[-1] = (items[-1][0] + " " + line, items[-1][1])
        out = []
        for item, isBullet in items:
            out += [item] if isBullet else [s.strip() for s in re.split(SENTENCE_END, item) if s.strip()]
        # greetings, sign-offs and template filler, dropped per sentence since they share
        # wrapped lines with real text
        out = [u for u in out if not BOILERPLATE.match(u) and not FILLER.search(u)]
        if out:
            paragraphs.append(out)
    return paragraphs


def label(sentence: str, firstParagraph: bool) -> str | None:
    if HELP_WORDS.search(sentence) or CALL_IF.search(sentence):
        return HELP
    if FOLLOW_WORDS.search(sentence):
        return FOLLOWUP
    if TODO_START.match(sentence):
        return TODO
    if firstParagraph and HAPPENED_WORDS.search(sentence):
        return HAPPENED
    return None


def sortInstructions(text: str) -> dict[str, list[str]]:
    """{section header: [doctor's sentences]}. Unclear sentences go with their neighbours.

    An intro line ending in ':' ("Call your doctor or return to the ED for any of the
    following:") passes its section to the bullets under it.
    """
    sections: dict[str, list[str]] = {h: [] for h in SECTION_HEADERS}
    for i, paragraph in enumerate(units(text)):
        labels = [label(s, i == 0) for s in paragraph]
        intro = None
        for j, s in enumerate(paragraph):
            if s.endswith(":") and j + 1 < len(paragraph):
                intro = labels[j]
                labels[j] = None
            elif labels[j] is None and intro:
                labels[j] = intro
        for j in range(len(labels)):
            if labels[j] is None:
                before = next((labels[k] for k in range(j - 1, -1, -1) if labels[k]), None)
                after = next((labels[k] for k in range(j + 1, len(labels)) if labels[k]), None)
                labels[j] = (after if paragraph[j].endswith(":") else before or after) or \
                    (HAPPENED if i == 0 else TODO)
        for s, lab in zip(paragraph, labels):
            sections[lab].append(s)
    return sections


def unitCount(text: str) -> int:
    return sum(len(p) for p in units(text))


def followupLines(note: str) -> list[str]:
    """Appointments from the note's own Followup Instructions section."""
    match = re.search(rf"\nFollowup Instructions[ \t]*:\s*(.*?){NEXT_HEADER}", "\n" + (note or ""),
                      re.DOTALL | re.IGNORECASE)
    if not match:
        return []
    lines = [l.strip(" -*\t") for l in match.group(1).splitlines()]
    return [l for l in lines if re.search(r"[A-Za-z]{3}", l.replace("___", ""))]


def renderSection(header: str, sentences: list[str]) -> str:
    if header == HAPPENED:
        return " ".join(sentences)
    out = []
    for s in sentences:
        out.append(s if s.endswith(":") else f"- {s}")
    return "\n".join(out)
