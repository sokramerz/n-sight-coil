"""Which listed side effects a patient should get help for right away.

The drug graph lists side effects as clinical terms in alphabetical order, with no
frequency or severity, and a drug can have hundreds. Nothing is dropped: every listed
effect stays available. The ones below are moved to the top, grouped under one plain
warning each, because they are dangerous and the patient can notice them at home.
Lab findings (high liver enzymes, low platelets) aren't on the list, since a patient
can't see them.

Written for the project; NEEDS CLINICIAN REVIEW like redflags.py and purposes.py.
"""
from __future__ import annotations

# plain warning -> the graph's terms for it
SERIOUS: dict[str, tuple[str, ...]] = {
    "A severe allergic reaction: trouble breathing, or swelling of the face, lips, tongue or throat":
        ("Anaphylactic shock", "Facial edema", "Laryngeal edema", "Pharyngeal edema", "Periorbital edema",
         "Palpebral edema"),
    "Trouble breathing or new shortness of breath":
        ("Respiratory distress", "Dyspnea", "Respiratory failure", "Apnea", "Respiratory arrest",
         "Pulmonary edema", "Exertional dyspnea"),
    "Chest pain": ("Chest pain",),
    "A heartbeat that is very fast, very slow, or uneven":
        ("Arrhythmia", "Tachycardia", "Bradycardia", "Ventricular tachycardia", "Ventricular arrhythmia",
         "Supraventricular tachycardia", "Supraventricular arrhythmia", "Prolonged QT interval",
         "Cardiac arrest", "Cardiorespiratory arrest", "Sinus bradycardia", "Sinus tachycardia"),
    "Fainting": ("Syncope",),
    "A seizure": ("Seizure",),
    "Sudden weakness on one side, trouble speaking, or a sudden severe headache":
        ("Ischemic stroke", "Cerebral hemorrhage", "Intracranial hemorrhage", "Subdural hemorrhage"),
    "Black or tarry stools, vomiting blood, or blood in your urine":
        ("Gastrointestinal hemorrhage", "Melena", "Hematemesis", "Hematuria"),
    "Bruising easily or bleeding that won't stop": ("Bruising susceptibility", "Prolonged bleeding time"),
    "Yellow skin or eyes": ("Jaundice", "Hepatitis", "Hepatic failure", "Fulminant hepatitis",
                            "Fulminant hepatic failure", "Acute hepatic failure"),
    "Severe pain in your upper belly that may spread to your back": ("Pancreatitis",),
    "Making much less urine than usual, or none":
        ("Oliguria", "Anuria", "Acute kidney injury", "Renal insufficiency"),
    "Low blood sugar: shaking, sweating, or sudden confusion": ("Hypoglycemia",),
    "New confusion, or seeing or hearing things that aren't there":
        ("Confusion", "Hallucinations", "Visual hallucinations", "Auditory hallucinations", "Coma"),
}

TERM_WARNING = {term.lower(): warning for warning, terms in SERIOUS.items() for term in terms}
WARNING_ORDER = {warning: i for i, warning in enumerate(SERIOUS)}


def rankSideEffects(effects: list[str]) -> dict:
    """{'getHelp': [{'warning', 'listedAs'}], 'other': [...], 'total': n}. Every effect lands in one of the two."""
    grouped: dict[str, list[str]] = {}
    other = []
    for effect in effects:
        warning = TERM_WARNING.get(effect.lower())
        if warning:
            grouped.setdefault(warning, []).append(effect)
        else:
            other.append(effect)
    getHelp = [{"warning": w, "listedAs": sorted(terms)}
               for w, terms in sorted(grouped.items(), key=lambda item: WARNING_ORDER[item[0]])]
    return {"getHelp": getHelp, "other": sorted(other, key=str.lower), "total": len(effects)}
