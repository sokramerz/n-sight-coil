"""Matching a discharge medication line to a standard drug name."""
from __future__ import annotations

import re

# common US and brand names that DrugBank files under another name
ALIASES = {
    "aspirin": ["acetylsalicylic acid"],
    "torsemide": ["torasemide"],
    "albuterol": ["salbutamol"],
    "glargine": ["insulin glargine"], "lantus": ["insulin glargine"], "basaglar": ["insulin glargine"],
    "toujeo": ["insulin glargine"],
    "humalog": ["insulin lispro"], "lispro": ["insulin lispro"],
    "novolog": ["insulin aspart"], "aspart": ["insulin aspart"],
    "ferrous sulfate": ["ferrous sulfate anhydrous"],
    "senna": ["sennosides"], "docusate sodium": ["docusate"],
    "tylenol": ["acetaminophen"], "lasix": ["furosemide"], "coumadin": ["warfarin"],
    "eliquis": ["apixaban"], "xarelto": ["rivaroxaban"], "plavix": ["clopidogrel"],
    "entresto": ["sacubitril", "valsartan"],
    "bactrim": ["sulfamethoxazole", "trimethoprim"],
    "augmentin": ["amoxicillin", "clavulanic acid"],
}
# words on a medication line that name the form or release, not the drug
FORM_WORDS = {"xl", "er", "sr", "cr", "dr", "ir", "xr", "ec", "odt", "hfa", "inhaler", "patch", "tablet", "tab",
              "capsule", "cap", "solution", "suspension", "injection", "flush", "cream", "ointment", "gel",
              "drops", "spray", "pen", "extended", "release", "delayed", "oral", "nebulizer", "neb", "chewable"}
# salt and ester names DrugBank usually leaves off the parent drug
SALT_WORDS = {"succinate", "tartrate", "bromide", "hydrochloride", "hcl", "sodium", "potassium", "calcium",
              "sulfate", "citrate", "maleate", "besylate", "mesylate", "fumarate", "phosphate", "acetate"}


def norm(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (text or "").lower()))


def candidates(medName: str) -> list[list[str]]:
    """Names to try for one medication line, best first. A combination drug gives several names."""
    name = norm(medName)
    words = [w for w in name.split() if w not in FORM_WORDS]
    base = " ".join(words)
    tries: list[list[str]] = [[name], [base]]
    if base in ALIASES:
        tries.append(ALIASES[base])
    parts = [norm(p) for p in re.split(r"[-/]| and ", (medName or "").lower()) if norm(p)]
    if len(parts) > 1:
        tries.append(parts)
    noSalt = " ".join(w for w in words if w not in SALT_WORDS)
    if noSalt and noSalt != base:
        tries.append([noSalt])
        if noSalt in ALIASES:
            tries.append(ALIASES[noSalt])
    for n in range(len(words) - 1, 0, -1):
        prefix = " ".join(words[:n])
        tries.append(ALIASES.get(prefix, [prefix]))
    return tries



# pharmacy "tall man" lettering (CefePIME, predniSONE, hydrALAZINE) marks look-alike names for staff
WORD = re.compile(r"\b[A-Za-z]{5,}\b")


def isTallMan(word: str) -> bool:
    upper = sum(c.isupper() for c in word)
    lower = sum(c.islower() for c in word)
    return lower >= 2 and (upper >= 3 or word[:2].isupper())


def plainCase(text: str | None) -> str | None:
    """'CefePIME 2 g' -> 'Cefepime 2 g'. The first letter keeps its case."""
    if not text:
        return text
    return WORD.sub(lambda m: m.group(0)[0] + m.group(0)[1:].lower() if isTallMan(m.group(0)) else m.group(0), text)
