"""Note sections, held-out targets, and the answer-key leak check."""
from __future__ import annotations

import re

TARGET_SECTIONS = ("Brief Hospital Course", "Discharge Instructions")

# real MIMIC-IV discharge summary headers; sections end only at one of these,
# never at sub-headers like "Disp:" or "Activity:"
NOTE_HEADERS = (
    "Name", "Unit No", "Admission Date", "Discharge Date", "Date of Birth", "Sex",
    "Service", "Allergies", "Attending", "Chief Complaint",
    "Major Surgical or Invasive Procedure", "History of Present Illness",
    "Past Medical History", "Social History", "Family History", "Physical Exam",
    "Pertinent Results", "Brief Hospital Course", "Medications on Admission",
    "Discharge Medications", "Discharge Disposition", "Discharge Diagnosis",
    "Discharge Condition", "Discharge Instructions", "Followup Instructions",
)
NEXT_HEADER = r"(?=\n(?:" + "|".join(map(re.escape, NOTE_HEADERS)) + r")[ \t]*:|\Z)"

LEAK_SHINGLE = 8


def removeSections(text: str, headers: tuple[str, ...]) -> str:
    """Drop whole note sections, header line included."""
    out = "\n" + (text or "")
    for header in headers:
        out = re.sub(rf"\n{re.escape(header)}[ \t]*:.*?{NEXT_HEADER}", "", out, flags=re.DOTALL)
    return out.lstrip("\n")


def shingles(text: str, n: int = LEAK_SHINGLE) -> set[str]:
    words = (text or "").split()
    return {" ".join(words[i:i + n]) for i in range(max(0, len(words) - n + 1))}


def leaks(modelInput: str | None, answerKey: str | None) -> bool:
    """True if any 8-word run from the answer key shows up in the model input."""
    if not answerKey:
        return False
    flat = " ".join((modelInput or "").split())
    return any(s in flat for s in shingles(" ".join(answerKey.split())))


def segment_document(cleaned_note: str, doc_id: str):
    raise NotImplementedError
