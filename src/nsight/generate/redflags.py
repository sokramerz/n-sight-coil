"""Standard warning signs, picked by discharge diagnosis, for when the doctor's note gives none.

Written for this project as general patient education, in plain words. They are not taken
from any patient record. Before any real use, a clinician has to review this list.

Most MIMIC discharge instructions (329 of our 500) say nothing about when to get help, and a
4B model asked to fill that gap invents signs and sends patients to the wrong place. A fixed,
reviewable list is safer than generated text.
"""
from __future__ import annotations

import re

from nsight.ingest.medications import BLOOD_THINNERS

CALL_911 = "call 911"
GO_ER = "go to the emergency room"
CALL_DOCTOR = "call your doctor"

# (name, diagnosis pattern, [(sign, action)])
CATEGORIES = (
    ("heart failure", r"heart failure|\bchf\b|hfref|hfpef|cardiomyopathy", [
        ("Your weight goes up quickly, by a few pounds in a day or two", CALL_DOCTOR),
        ("More swelling in your legs, feet, or belly", CALL_DOCTOR),
        ("You get short of breath lying flat or need more pillows to sleep", CALL_DOCTOR),
    ]),
    ("coronary", r"\bn?stemi\b|myocardial infarction|\bacs\b|angina|coronary", [
        ("Chest pain or pressure, or pain that spreads to your arm, jaw, or back", CALL_911),
    ]),
    ("arrhythmia", r"atrial fib|\bafib\b|a-fib|flutter|arrhythm|tachycardia|bradycardia", [
        ("Your heart races or pounds and does not slow down", GO_ER),
    ]),
    ("stroke", r"stroke|\bcva\b|\btia\b", [
        ("Your face droops, one arm or leg is weak, or you have trouble speaking", CALL_911),
    ]),
    ("seizure", r"seizure|epilep", [
        ("You have a seizure", CALL_911),
    ]),
    ("lungs", r"pneumonia|copd|asthma|emphysema|bronchitis|respiratory failure", [
        ("It is harder to breathe than when you left the hospital", CALL_DOCTOR),
        ("Your lips or fingertips turn blue, or you are too short of breath to talk", CALL_911),
    ]),
    ("infection", r"sepsis|bacteremia|\buti\b|urinary tract infection|pyelonephritis|cellulitis|abscess|"
                  r"osteomyelitis|infection|pneumonia", [
        ("A fever or shaking chills", CALL_DOCTOR),
        ("Redness, warmth, or pus around a wound or IV line", CALL_DOCTOR),
        ("You feel confused or much weaker", GO_ER),
    ]),
    ("gi bleed", r"gi bleed|gastrointestinal (bleed|hemorrhage)|ulcer|melena|hematochezia|varic", [
        ("Black or bloody stool, or vomit that has blood or looks like coffee grounds", GO_ER),
        ("You feel dizzy or faint", GO_ER),
    ]),
    ("liver", r"cirrhosis|hepatic|liver|ascites", [
        ("You become confused or very sleepy", GO_ER),
        ("Your belly swells quickly, or your skin or eyes turn more yellow", CALL_DOCTOR),
    ]),
    ("diabetes", r"diabet|\bdka\b|hyperglyc|hypoglyc", [
        ("Your blood sugar stays much higher or lower than your target", CALL_DOCTOR),
        ("You are vomiting and cannot keep fluids down", GO_ER),
    ]),
    ("kidney", r"acute kidney|\baki\b|renal failure|\bckd\b|\besrd\b", [
        ("You make much less urine than usual", CALL_DOCTOR),
    ]),
    ("clot", r"\bdvt\b|deep vein|pulmonary embol", [
        ("New swelling or pain in one leg", CALL_DOCTOR),
        ("Sudden shortness of breath or chest pain", CALL_911),
    ]),
    ("pancreas or belly", r"pancreatitis|cholecyst|colitis|diverticul|bowel obstruction|abdominal pain", [
        ("Belly pain that gets worse, or you cannot keep food or fluids down", GO_ER),
    ]),
)

BLEEDING = [("Bleeding that will not stop, blood in your urine or stool, or a fall where you hit your head",
             GO_ER)]
ALWAYS = [("Chest pain, trouble breathing, or fainting", CALL_911)]
MAX_SIGNS = 6


def warningSigns(diagnoses: list[str], medicationsSection: str | None) -> list[str]:
    """Bullets for 'When to get help right away', most specific first, ending with the emergencies."""
    text = " ".join(diagnoses or []).lower()
    signs: list[tuple[str, str]] = []
    # bleeding first: on a blood thinner it matters whatever the diagnosis
    meds = (medicationsSection or "").lower()
    if any(drug in meds for drug in BLOOD_THINNERS):
        signs += BLEEDING
    for _, pattern, items in CATEGORIES:
        if re.search(pattern, text):
            signs += items
    seen: set[str] = set()
    unique = [s for s in signs if not (s[0] in seen or seen.add(s[0]))]
    picked = unique[:MAX_SIGNS - 1] + ALWAYS
    return [f"{sign}: {action}." for sign, action in picked]
