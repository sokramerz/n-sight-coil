"""Patient-facing text as plain strings plus spans for the frontend to style.

Generated sections carry glossary explanations written into the text in
parentheses, which makes some lines hard to read. Here they come back out of the
text and become spans on the term, along with spans for details removed from the
record for privacy and for the patient's own conditions. The text is never
markup: the frontend renders the text between spans as-is.

Offsets are UTF-16 code units, the way JavaScript strings index.
"""
from __future__ import annotations

import re

from nsight.generate.glossary import COMPILED as GLOSSARY

REMOVED = "[redacted]"
ASIDES = re.compile(r" ?\((?:" + "|".join(re.escape(e) for _, _, e in GLOSSARY) + r")\)")

BEFORE_NAME = re.compile(r"\b(?:Dr|Doctor|Mr|Mrs|Ms|NP|PA)\.?,?\s*$", re.IGNORECASE)
BEFORE_DATE = re.compile(r"\b(?:until|through|by|on|before|after|starting|from|since|end date|date)\s*:?\s*$",
                         re.IGNORECASE)
AFTER_DATE = re.compile(r"^\s*(?:at\s+\d{1,2}(?::\d{2})?\s*(?:AM|PM)|\d{1,2}:\d{2})", re.IGNORECASE)
PHONE_CONTEXT = re.compile(r"\b(?:call|phone|number|tel|telephone|reach|contact)\b", re.IGNORECASE)


def utf16(text: str, index: int) -> int:
    return len(text[:index].encode("utf-16-le")) // 2


def removedLabel(text: str, start: int, end: int) -> str:
    """What kind of detail was removed, from the words around it."""
    before, after = text[:start], text[end:]
    if BEFORE_NAME.search(before):
        return "name"
    if AFTER_DATE.search(after) or BEFORE_DATE.search(before):
        return "date"
    if PHONE_CONTEXT.search(before[-40:]):
        return "phone number"
    return "detail"


def termSpans(text: str, seen: set[str]) -> list[dict]:
    """The first use of each glossary term in the document, with its explanation."""
    spans = []
    for label, pattern, explanation in GLOSSARY:
        if label in seen:
            continue
        match = pattern.search(text)
        if match:
            seen.add(label)
            spans.append({"start": match.start(), "end": match.end(), "kind": "term", "explanation": explanation})
    return spans


def removedSpans(text: str) -> list[dict]:
    spans = []
    for match in re.finditer(re.escape(REMOVED), text):
        spans.append({"start": match.start(), "end": match.end(), "kind": "removed",
                      "label": removedLabel(text, match.start(), match.end())})
    return spans


def merge(spans: list[dict]) -> list[dict]:
    """Sorted and non-overlapping. A condition that is also a glossary term keeps the explanation."""
    spans = sorted(spans, key=lambda s: (s["start"], -(s["end"] - s["start"])))
    out: list[dict] = []
    for span in spans:
        clash = next((s for s in out if span["start"] < s["end"] and s["start"] < span["end"]), None)
        if clash is None:
            out.append(span)
        elif span["kind"] == "condition" and clash["kind"] == "term":
            out[out.index(clash)] = {**span, "explanation": clash["explanation"]}
        elif span["kind"] == "term" and clash["kind"] == "condition":
            clash.setdefault("explanation", span["explanation"])
    return sorted(out, key=lambda s: s["start"])


def richSections(sections: list[list[str]], conditionLinks=None) -> list[list[dict]]:
    """Section -> item -> {'text', 'spans'}, in reading order so each term is explained once.

    `conditionLinks(cleanSections)` returns the term links from HealthInfo.termLinks.
    """
    clean = [[" ".join(ASIDES.sub("", item).split()) for item in items] for items in sections]
    links = conditionLinks(clean) if conditionLinks else []
    seen: set[str] = set()
    out = []
    for si, items in enumerate(clean):
        rich = []
        for ii, text in enumerate(items):
            spans = termSpans(text, seen) + removedSpans(text)
            spans += [{"start": l["start"], "end": l["end"], "kind": "condition", "topicId": l["topicId"],
                       "title": l["title"]} for l in links if l["section"] == si and l["item"] == ii]
            spans = merge(spans)
            for span in spans:
                span["start"], span["end"] = utf16(text, span["start"]), utf16(text, span["end"])
            rich.append({"text": text, "spans": spans})
        out.append(rich)
    return out


GLOSSARY_STYLES = ("separate", "inline")
REMOVED_TEXT = {"name": "[name on your paperwork]", "date": "[date on your paperwork]",
                "phone number": "[phone number on your paperwork]", "detail": "[see your paperwork]"}
PLURAL_ABBREVIATION = re.compile(r"^[A-Z]{2,}s$")


def spanText(text: str, span: dict) -> str:
    raw = text.encode("utf-16-le")
    return raw[span["start"] * 2:span["end"] * 2].decode("utf-16-le")


def explanationSentence(term: str, explanation: str) -> str:
    """'PICC line', 'a thin tube...' -> 'A PICC line is a thin tube...'; 'IV' -> 'IV means through a vein.'"""
    if PLURAL_ABBREVIATION.match(term) or (term.endswith("s") and not term.endswith(("ss", "is", "us"))
                                          and not re.match(r"(?:a|an|the) ", explanation)):
        verb = "are"
    elif re.match(r"(?:a|an|the) ", explanation):
        verb = "is"
    else:
        verb = "means"
    # "PICC line" reads as a thing ("A PICC line is"); "TTE" or "C. diff" reads as a name
    words = term.split()
    named = len(words) > 1 and words[0].isalpha() and words[0].isupper() and words[-1].isalpha() and words[-1].islower()
    subject = f"A {term}" if verb == "is" and named else term
    sentence = f"{subject} {verb} {explanation}."
    return sentence[0].upper() + sentence[1:]


def labelRemoved(text: str, labels: list[str]) -> str:
    """Swap each [redacted] for what kind of detail it was, in order."""
    parts = text.split(REMOVED)
    out = parts[0]
    for i, part in enumerate(parts[1:]):
        out += REMOVED_TEXT.get(labels[i] if i < len(labels) else "detail", REMOVED_TEXT["detail"]) + part
    return out


def styledItem(original: str, rich: dict, style: str) -> str:
    """The item as the patient reads it.

    inline: explanations in parentheses right after the word, as generated.
    separate: the doctor's sentence first, then one short sentence per explained word, each on its own line.
    """
    labels = [s["label"] for s in rich["spans"] if s["kind"] == "removed"]
    if style == "inline":
        return labelRemoved(original, labels)
    lines = [labelRemoved(rich["text"], labels)]
    lines += [explanationSentence(spanText(rich["text"], s), s["explanation"])
              for s in rich["spans"] if s.get("explanation")]
    return "\n".join(lines)
