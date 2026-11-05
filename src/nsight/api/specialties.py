"""Find cases by specialty so a physician can review the ones in their field.

A case matches on its discharge diagnoses, its discharge medicines, or the past
medical history in the note (a patient on dialysis is a kidney case even when this
stay was for something else). Each match says why, so the reviewer can see it.
Only nephrology is defined so far; add a specialty by adding an entry to SPECIALTIES.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from nsight.ingest.segmentation import NEXT_HEADER


@dataclass(frozen=True)
class Specialty:
    label: str
    diagnoses: re.Pattern
    medicines: re.Pattern
    history: re.Pattern


SPECIALTIES = {
    "nephrology": Specialty(
        label="Kidney (nephrology)",
        diagnoses=re.compile(
            r"(?i:kidney|\brenal|nephr|glomerul|dialysis|uremi|hyperkalemi|hyponatremi|hypernatremi|"
            r"acute tubular necrosis)|\b(?:CKD|ESRD|ESKD|AKI|ATN|ARF|FSGS)\b"),
        medicines=re.compile(r"(?i:\b(?:sevelamer|lanthanum|calcium acetate|cinacalcet|epoetin|darbepoetin|"
                             r"patiromer|sodium zirconium|sodium polystyrene|nephrocaps)\b)"),
        history=re.compile(r"(?i:hemodialysis|peritoneal dialysis|(?:kidney|renal) transplant|"
                           r"end[- ]stage renal|chronic kidney disease)|\b(?:ESRD|ESKD|DDRT|LRRT|CKD)\b"),
    ),
}

HISTORY_SECTION = re.compile(rf"\nPast Medical History[ \t]*:(.*?){NEXT_HEADER}", re.DOTALL | re.IGNORECASE)


def pastHistory(note: str | None) -> str:
    match = HISTORY_SECTION.search("\n" + (note or ""))
    return match.group(1) if match else ""


def caseReasons(specialty: Specialty, diagnoses: list[str], medicines: list[str], note: str | None) -> list[str]:
    """Why an admission belongs to the specialty, or [] when it doesn't."""
    reasons = [d for d in diagnoses if specialty.diagnoses.search(d)]
    reasons += [f"Takes {m}" for m in medicines if specialty.medicines.search(m)]
    history = specialty.history.search(pastHistory(note))
    if history:
        reasons.append(f"History: {history.group(0)}")
    return reasons
