"""Parse the discharge medication and allergy sections, and translate pharmacy shorthand."""
from __future__ import annotations

import re
from dataclasses import dataclass

from nsight.ingest.cleaning import stripPlaceholders

MED_NOISE = {
    "tablet", "tablets", "capsule", "capsules", "mg", "mcg", "ml", "unit",
    "units", "po", "iv", "daily", "bid", "tid", "qid", "prn", "oral", "qhs",
    "every", "hours", "hour", "day", "days", "times", "refills", "disp",
    "sig", "one", "two", "by", "mouth", "as", "needed", "for", "and", "the",
    "solution", "injection", "puff", "inhalation", "subcutaneous", "release",
    "extended", "delayed", "patch", "cream", "ointment", "drop", "drops",
    "redacted", "home", "none", "with", "take", "each", "week", "weeks",
}

# order-status words that come before the drug name
MED_PREFIX = re.compile(
    r"^\s*(held|hold|holding|continue|continued|stop|stopped|start|started|"
    r"resume|resumed|new|changed|increase|decrease)\b[\s\-:]*",
    re.IGNORECASE,
)
MED_REJECT = re.compile(r"^(none|no |n/a|see |per |same)", re.IGNORECASE)
MED_LINE = re.compile(r"^\s*\d+\s*[\.\)]\s*(.+)$")
ENTRY_SPLIT = re.compile(r"\n(?=\s*\d+\s*[.)]\s)")

# meds where leaving one out can cause immediate harm
HIGH_RISK_STEMS = (
    "warfarin", "apixaban", "rivaroxaban", "dabigatran", "enoxaparin",
    "heparin", "clopidogrel", "ticagrelor", "prasugrel", "insulin",
    "metformin", "glipizide", "glyburide", "digoxin", "amiodarone",
    "methotrexate", "prednisone", "levothyroxine", "lithium", "phenytoin",
)


def drugKey(entryText: str) -> str | None:
    """Lowercase first word of the drug name, used for matching."""
    candidate = MED_PREFIX.sub("", entryText)
    if MED_REJECT.match(candidate):
        return None
    candidate = re.split(r"\d", candidate)[0]
    candidate = re.sub(r"[^A-Za-z\s\-]", " ", candidate)
    tokens = candidate.lower().split()
    # first real word only, otherwise "Ferrous Sulfate" becomes "sulfate"
    head = next((t for t in tokens if len(t) > 2), None)
    if head is None or head in MED_NOISE or len(head) <= 3:
        return None
    return head


def drugName(entryText: str) -> str:
    """Display name: everything before the first digit, prefix words removed."""
    name = MED_PREFIX.sub("", entryText)
    name = re.split(r"\s\d|\(\d", name)[0]
    name = re.sub(r"\bSig:.*$", "", name)
    return " ".join(name.split()).strip(" -:,")


def parseMedications(section: str | None) -> list[str]:
    if not section:
        return []
    meds = []
    for line in splitContinuations(section).splitlines():
        match = MED_LINE.match(line)
        if match and not isOrder(match.group(1)):
            key = drugKey(match.group(1))
            if key:
                meds.append(key)
    return sorted(set(meds))


def parseAllergies(section: str | None) -> list[str]:
    if not section:
        return []
    text = section.strip().lower()
    if "no known" in text or text in {"none", "nka", "nkda", ""}:
        return []
    cleaned = []
    for part in re.split(r"[,\n/;]| and ", text):
        part = re.sub(r"\(.*?\)", "", part)
        part = re.sub(r"[^a-z\s\-]", " ", part).strip()
        if len(part) > 3 and "___" not in part:
            cleaned.append(part.split()[0])
    return sorted(set(cleaned))


def allergyLines(section: str | None) -> list[str]:
    """Allergies as the clinician listed them, one per line, for display."""
    cleaned = stripPlaceholders(section)
    if not cleaned or "no known" in cleaned.lower():
        return []
    parts = [p.strip(" .") for p in re.split(r"\s*/\s*|\n|;", cleaned)]
    return [p for p in parts if p and "[redacted]" not in p]


def isHighRisk(med: str) -> bool:
    return any(med.startswith(stem[:6]) for stem in HIGH_RISK_STEMS)


# pharmacy shorthand to plain language, whole tokens only, so names and doses are never touched
SIG_TERMS = [
    (r"\bQ\s?(\d+)\s?-\s?(\d+)\s?H(?:RS?|OURS)?\b", r"every \1 to \2 hours"),
    (r"\bQ\s?(\d+)\s?H(?:RS?|OURS)?\b", r"every \1 hours"),
    (r"\bQHS\b", "at bedtime"),
    (r"\bQAM\b", "every morning"),
    (r"\bQPM\b", "every evening"),
    (r"\bQOD\b", "every other day"),
    (r"\bBID\b", "twice a day"),
    (r"\bTID\b", "3 times a day"),
    (r"\bQID\b", "4 times a day"),
    (r"\bDAILY\b", "once a day"),
    (r"\bPRN\b", "as needed"),
    (r"\bPO\b", "by mouth"),
    (r"\bSL\b", "under the tongue"),
    (r"\b(SC|SQ)\b", "injected under the skin"),
    (r"\bIV\b", "into a vein"),
    (r"\bPR\b", "rectally"),
    (r"\bTP\b", "on the skin"),
    (r"\bNU\b", "in the nose"),
    (r"\bINH\b", "inhaled"),
    (r"\bIH\b", "inhaled"),
    (r"\bTD\b", "on the skin"),
    (r"\bNEB\b", "by nebulizer"),
    (r"\bTABS?\b", "tablet"),
    (r"\bCAPS?\b", "capsule"),
    (r"\bPUFFS?\b", "puffs"),
    (r"\bW/MEALS\b", "with meals"),
    (r"\bDuration:\s*(\d+)\s*(Day|Week|Month)s?\b", lambda m: f"for {m.group(1)} {m.group(2).lower()}"
     + ("s" if m.group(1) != "1" else "")),
    (r"(?<!at )\bBedtime\b", "at bedtime"),
    (r"\bAPPL\b", "application"),
    (r"\bSPRY\b", "spray"),
]
FREQ_CODES = r"(?:Q\s?\d+(?:\s?-\s?\d+)?\s?H(?:RS?)?|QHS|QAM|QPM|QOD|BID|TID|QID|DAILY)(?:\s+W/MEALS)?"
NUM_WORD = (r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
            r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
            r"twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|half)")
DOSE = re.compile(r"(\d+(?:\.\d+)?)\s*(mg|mcg|gram|grams|g|units?|ml|meq|%)\b", re.IGNORECASE)


# pharmacy fields that follow the instructions: "RX *...", "Disp #*17 Vial", "Refills:*0"
PHARMACY_TAIL = re.compile(r"\s*(?:\bRX\s*\*|\bDisp\b\s*[:#]).*$", re.IGNORECASE)


def stripPharmacy(line: str) -> str:
    line = PHARMACY_TAIL.sub("", line)
    return re.sub(r"Refills:\s*\*?\d*\*?", "", line)


def simplifySig(line: str) -> str:
    line = stripPharmacy(line)
    line = line.replace("*NF*", "")
    line = re.sub(r"\bSig:\s*", "", line)
    # MIMIC often follows a code with its own expansion: "BID (2 times a day)"
    line = re.sub(rf"\b({FREQ_CODES})\s*\([^)]*\)", r"\1", line)
    # "One (1) Tablet" -> "1 Tablet", spelled-out numbers only
    line = re.sub(rf"\b{NUM_WORD}(?:[\s-]+(?:{NUM_WORD}|and))*\s*\((\d+(?:\.\d+)?)\)",
                  r"\1", line, flags=re.IGNORECASE)
    line = re.sub(r":(?=\s*PRN)", " ", line)
    line = re.sub(r"\bPRN\s+(?=[a-z])", "as needed for ", line)
    for pattern, plain in SIG_TERMS:
        line = re.sub(pattern, plain, line)
    line = re.sub(r"\s{2,}", " ", line)
    return line.strip(" .;")


def dosesPreserved(original: str, plain: str) -> bool:
    flat = " ".join(plain.split()).lower()
    for number, unit in DOSE.findall(stripPharmacy(original)):
        if f"{number} {unit}".lower() not in flat and f"{number}{unit}".lower() not in flat:
            return False
    return True


# lines in the medication list that are orders, not drugs: labs, therapy, equipment
ORDER_LINE = re.compile(
    r"^\s*(outpatient\b|durable medical equipment|\bDME\b|rolling walker|walker\b|wheelchair|"
    r"commode|cane\b|hospital bed|shower chair|glucometer|lancets?\b|(blood )?glucose (test )?strips?|"
    r"test strips?|ketone|compression stockings?|supplies\b|home (health|PT|OT|nursing|oxygen)|"
    r"oxygen concentrator|pulse oximeter|pen needles|insulin syringes|nebulizer machine)", re.IGNORECASE)

# MIMIC lists mealtime insulin on an unnumbered line under the basal insulin
INSULIN_CONTINUATION = re.compile(
    r"\n(?=[ \t]*(?:humalog|novolog|lispro|aspart|admelog|apidra|fiasp|humulin|regular insulin)\b)",
    re.IGNORECASE)

# drugs a patient should know are blood thinners, labelled in the medication list
BLOOD_THINNERS = ("warfarin", "coumadin", "apixaban", "eliquis", "rivaroxaban", "xarelto", "dabigatran",
                  "edoxaban", "enoxaparin", "lovenox", "heparin", "clopidogrel", "plavix", "ticagrelor",
                  "brilinta", "prasugrel")


def splitContinuations(section: str) -> str:
    return INSULIN_CONTINUATION.sub("\n0. ", section)
ORDER_TAIL = re.compile(
    r"\s*(?:\bICD[- ]?(?:9|10)\b|\bICD\b|\bDx\b|\bDiagnosis\b|\bContact\b|\bFax\b|\bPhone\b|"
    r"\bResults? to\b|\bPlease (?:fax|send)\b|\bLength of need\b|\bPrognosis\b).*$", re.IGNORECASE)


def isOrder(text: str) -> bool:
    return bool(ORDER_LINE.match(MED_PREFIX.sub("", text)))


def plainOrder(text: str) -> str:
    """'Outpatient Lab Work Bloodwork: CBC ICD-9: V42.0 Contact: ...' -> 'Lab Work Bloodwork: CBC'."""
    text = ORDER_TAIL.sub("", stripPharmacy(text))
    text = re.sub(r"^\s*outpatient\s+", "", text, flags=re.IGNORECASE)
    return " ".join(text.split()).strip(" .;:,")


@dataclass
class MedicationEntry:
    index: int
    name: str
    key: str | None
    original: str
    plain: str
    highRisk: bool
    kind: str = "med"


def parseMedicationEntries(section: str | None) -> list[MedicationEntry]:
    """One entry per numbered line, with a plain-language version of the instructions.

    If translating a line would change any dose, the original wording is kept.
    """
    cleaned = stripPlaceholders(section)
    if not cleaned:
        return []
    cleaned = splitContinuations(cleaned)
    entries: list[MedicationEntry] = []
    for chunk in ENTRY_SPLIT.split(cleaned):
        chunk = " ".join(chunk.split())
        chunk = re.sub(r"\s*Reason for Ordering:.*$", "", chunk, flags=re.IGNORECASE)
        match = MED_LINE.match(chunk)
        if not match:
            continue
        body = match.group(1)
        if isOrder(body):
            entries.append(MedicationEntry(index=0, name=plainOrder(body), key=None, original=body,
                                           plain=plainOrder(body), highRisk=False, kind="order"))
            continue
        plain = simplifySig(body)
        if not dosesPreserved(body, plain):
            plain = body
        key = drugKey(body)
        if any(body.lower().startswith(t) or (key and key.startswith(t[:6])) for t in BLOOD_THINNERS):
            plain += " (blood thinner)"
        entries.append(MedicationEntry(
            index=sum(e.kind == "med" for e in entries) + 1,
            name=drugName(body),
            key=key,
            original=body,
            plain=plain,
            highRisk=bool(key and isHighRisk(key)),
        ))
    return entries


def renderMedications(section: str | None) -> str:
    entries = [e for e in parseMedicationEntries(section) if e.kind == "med"]
    if not entries:
        return "No medications were listed at discharge."
    return "\n".join(f"{e.index}. {e.plain}" for e in entries)


def renderOrders(section: str | None) -> str:
    """Tests, therapy and equipment that were ordered in the medication list."""
    return "\n".join(f"- {e.plain}" for e in parseMedicationEntries(section) if e.kind == "order")


def renderAllergies(section: str | None) -> str:
    lines = allergyLines(section)
    return "\n".join(lines) if lines else "No known allergies."
