"""Plain-language explanations for medical abbreviations and jargon.

The first time a term appears in a document it gets a short explanation in
parentheses. This is fixed text, not model output, so it can't invent anything,
but it was written for the project and NEEDS CLINICIAN REVIEW like redflags.py.

Explanations carry no digits so they never trip the unsupported-number check.
Ambiguous abbreviations (PE, PT, HD, K) are left out on purpose.
"""
from __future__ import annotations

import re

# (label, pattern, explanation). Abbreviations match case-sensitively, words don't.
TERMS: list[tuple[str, str, str]] = [
    # tests
    ("INR", r"\bINR\b", "a blood test that shows how long your blood takes to clot"),
    ("CBC", r"\bCBC\b", "a blood test that counts your blood cells"),
    ("BMP", r"\bBMP\b", "a blood test that checks your kidneys, blood sugar, and body salts"),
    ("CMP", r"\bCMP\b", "a blood test that checks your kidneys, liver, blood sugar, and body salts"),
    ("LFTs", r"\bLFTs?\b", "blood tests that check your liver"),
    ("A1c", r"\b(?:Hb)?A1[cC]\b", "a blood test that shows your average blood sugar over the past few months"),
    ("creatinine", r"(?i:\bcreatinine\b)", "a blood test that shows how well your kidneys work"),
    ("CT", r"\bCT\b", "a scan that uses X-rays to take detailed pictures inside your body"),
    ("MRI", r"\bMRI\b", "a scan that uses magnets to take detailed pictures inside your body"),
    ("EKG", r"\b(?:EKG|ECG)\b", "a test that checks your heart's rhythm"),
    ("echo", r"\b(?:TTE|TEE)\b|(?i:\bechocardiogram\b)", "an ultrasound of your heart"),
    ("BP", r"\bBP\b", "blood pressure"),
    # places and people
    ("PCP", r"\bPCP\b", "your main doctor"),
    ("ED", r"\b(?:ED|ER)\b", "emergency room"),
    ("ICU", r"\bICU\b", "intensive care unit"),
    ("SNF", r"\bSNF\b", "a nursing facility where you get care while you recover"),
    ("VNA", r"\bVNA\b", "visiting nurse"),
    ("GI", r"\bGI\b", "stomach and intestines"),
    # conditions
    ("CHF", r"\bCHF\b", "congestive heart failure, when the heart does not pump as well as it should"),
    ("COPD", r"\bCOPD\b", "a long-term lung disease that makes it hard to breathe"),
    ("DVT", r"\bDVT\b", "a blood clot in a deep vein, usually in the leg"),
    ("UTI", r"\bUTI\b", "an infection of the bladder or kidneys"),
    ("CKD", r"\bCKD\b", "long-term kidney disease"),
    ("ESRD", r"\bESRD\b", "kidney failure, when the kidneys no longer work well enough on their own"),
    ("MI", r"\bMI\b", "heart attack"),
    ("AFib", r"\bA-?[Ff]ib\b|(?i:\batrial fibrillation\b)", "an irregular heartbeat"),
    ("C. diff", r"\bC\.\s?diff(?:icile)?\b|\bCdiff\b|(?i:\bclostridium difficile\b)", "a germ that causes serious diarrhea"),
    ("MRSA", r"\bMRSA\b", "a staph germ that many antibiotics cannot kill"),
    ("CABG", r"\bCABG\b", "heart bypass surgery"),
    ("hypertension", r"(?i:\bhypertension\b)", "high blood pressure"),
    ("edema", r"(?i:\bedema\b)", "swelling"),
    ("dyspnea", r"(?i:\bdyspnea\b)", "shortness of breath"),
    ("syncope", r"(?i:\bsyncope\b)", "fainting"),
    ("erythema", r"(?i:\berythema\b)", "redness"),
    # treatments and devices
    ("PICC", r"\bPICC(?: line)?\b", "a thin tube in a vein, used to give medicine"),
    ("IV", r"\bIV\b", "through a vein"),
    ("NSAIDs", r"\bNSAIDs?\b", "pain medicines like ibuprofen and naproxen"),
    ("anticoagulation", r"(?i:\banticoagula(?:tion|nts?)\b)", "blood thinning medicine"),
    ("sutures", r"(?i:\bsutures\b)", "stitches"),
    # dosing shorthand that slips into the narrative
    ("PO", r"\bPO\b", "by mouth"),
    ("PRN", r"\bPRN\b", "only when needed"),
    ("BID", r"\bBID\b", "twice a day"),
    ("TID", r"\bTID\b", "three times a day"),
    ("QID", r"\bQID\b", "four times a day"),
    ("QHS", r"\bQHS\b", "at bedtime"),
]

PAREN_AFTER = re.compile(r"\s?\(([^()]*)\)")

COMPILED = [(label, re.compile(pattern), explanation) for label, pattern, explanation in TERMS]


def explainTerms(text: str, seen: set[str]) -> tuple[str, list[str]]:
    """Add an explanation after the first use of each term not already in `seen`."""
    added = []
    for label, pattern, explanation in COMPILED:
        if label in seen:
            continue
        match = pattern.search(text)
        if not match:
            continue
        seen.add(label)
        end = match.end()
        aside = PAREN_AFTER.match(text, end)
        if aside:
            # a few words in parentheses means it's already explained; one is just a nickname
            if len(aside.group(1).split()) >= 2:
                continue
            end = aside.end()
        text = f"{text[:end]} ({explanation}){text[end:]}"
        added.append(label)
    return text, added


def explainSections(sections: list[dict]) -> tuple[list[dict], list[str]]:
    """Explain each term once per document, at its first appearance in reading order."""
    seen: set[str] = set()
    out, added = [], []
    for section in sections:
        text, terms = explainTerms(section["text"], seen)
        out.append({**section, "text": text})
        added += terms
    return out, added
