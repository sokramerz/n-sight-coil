"""What changed between the medicines a patient came in on and the ones they leave with.

Compares the note's "Medications on Admission" list with "Discharge Medications".
Everything here comes from those two lists; nothing is generated.
"""
from __future__ import annotations

import re

from nsight.ingest.drugnames import ALIASES, FORM_WORDS, SALT_WORDS, norm
from nsight.ingest.medications import MedicationEntry, parseMedicationEntries
from nsight.ingest.segmentation import NEXT_HEADER

ADMISSION_SECTION = re.compile(rf"\nMedications on Admission[ \t]*:(.*?){NEXT_HEADER}", re.DOTALL | re.IGNORECASE)
INCOMPLETE = re.compile(r"incomplete|require[sd]? (?:further|futher) investigation|unable to (?:obtain|verify)",
                        re.IGNORECASE)


def admissionSection(note: str | None) -> str | None:
    match = ADMISSION_SECTION.search("\n" + (note or ""))
    return match.group(1).strip() if match else None


def identity(name: str) -> str:
    """One key per drug, whatever the form, salt or brand: 'Metoprolol Succinate XL' -> 'metoprolol'."""
    words = [w for w in norm(name).split() if w not in FORM_WORDS]
    base = " ".join(words)
    if base in ALIASES:
        return " + ".join(ALIASES[base])
    noSalt = " ".join(w for w in words if w not in SALT_WORDS) or base
    return " + ".join(ALIASES.get(noSalt, [noSalt]))


STRENGTH = re.compile(r"(\d+(?:\.\d+)?)\s*(mg|mcg|g|grams?|units?|ml|meq|%)\b", re.IGNORECASE)
QUANTITY = re.compile(r"\b(\d+(?:\.\d+)?|one|two|three|half)\s*(tablets?|tabs?|capsules?|caps?|puffs?|patch(?:es)?)\b",
                      re.IGNORECASE)
TIMING = re.compile(r"once a day|twice a day|three times a day|four times a day|every \d+(?:-\d+)? hours?|"
                    r"every other day|once a week|at bedtime|every (?:morning|evening|night)|with meals|"
                    r"as needed|for \d+ (?:days?|weeks?)", re.IGNORECASE)
WORD_NUMBERS = {"one": "1", "two": "2", "three": "3", "half": "0.5"}


def dosing(entry: MedicationEntry) -> tuple:
    """Strength, how many, and when: the parts of a medicine line that make a dose change.

    Wording differences between the two lists ("5 mg Tablet 1 Tablet" vs "5 mg") don't count.
    """
    text = entry.plain
    strengths = tuple(sorted(f"{float(n):g} {u.lower().rstrip('s').replace('gram', 'g')}" for n, u in STRENGTH.findall(text)))
    quantity = tuple(sorted(f"{float(WORD_NUMBERS.get(n.lower(), n)):g}" for n, _ in QUANTITY.findall(text))) or ("1",)
    timing = tuple(sorted(t.lower() for t in TIMING.findall(text)))
    return strengths, quantity, timing


def medicationChanges(note: str | None, dischargeSection: str | None) -> dict:
    """new / stopped / changed / unchanged, or available=False when there's no admission list to compare."""
    section = admissionSection(note)
    before = [e for e in parseMedicationEntries(section) if e.kind == "med"]
    after = [e for e in parseMedicationEntries(dischargeSection) if e.kind == "med"]
    result = {"available": bool(before), "admissionListIncomplete": bool(section and INCOMPLETE.search(section)),
              "new": [], "stopped": [], "changed": [], "unchanged": []}
    if not before:
        return result
    old = {identity(e.name): e for e in before}
    new = {identity(e.name): e for e in after}
    for key, entry in new.items():
        if key not in old:
            result["new"].append({"name": entry.name, "now": entry.plain})
        elif dosing(old[key]) != dosing(entry):
            result["changed"].append({"name": entry.name, "before": old[key].plain, "now": entry.plain})
        else:
            result["unchanged"].append(entry.name)
    for key, entry in old.items():
        if key not in new:
            result["stopped"].append({"name": entry.name, "before": entry.plain})
    return result
