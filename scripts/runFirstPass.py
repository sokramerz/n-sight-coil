"""n-sight first pass: summarize and shorten, then measure what went missing.

No simplification yet. The question this answers is narrow: when the model
compresses a discharge summary, does it keep the facts a patient needs?

Scorecard per admission:
    medRecall            fraction of discharge medications that survived
    dxRecall             fraction of discharge diagnoses that survived
    allergyRecall        fraction of allergies that survived
    criticalOmissions    count of never-suppress items missing (target: 0)
    compressionRatio     output length / input length
    fkGrade              Flesch-Kincaid grade level, tracked but not optimized yet

    python scripts/runFirstPass.py --input data/cohort.json --n 50
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

import requests
import textstat

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "medgemma:4b"          # dev tier; never report numbers from this
TEMPERATURE = 0.2
MAX_INPUT_CHARS = 24000        # crude guard; real token budgeting comes later

PROMPT = """You are writing the discharge instructions a patient will take home.

Use ONLY the information in the record below. Do not add advice, diagnoses, or
medications that do not appear in it. If something is not in the record, leave
it out.

Cover, in this order:
1. What happened during this hospital stay, briefly.
2. What the patient needs to do over the next few days.
3. Medications: what to take, and any that were started, stopped or changed.
4. What to watch for and when to seek help.
5. Follow-up: who to contact and when.

RECORD:
{record}

DISCHARGE INSTRUCTIONS:"""


# Stop tokens that appear in medication sections but are not drug names.
MED_NOISE = {
    "tablet", "tablets", "capsule", "capsules", "mg", "mcg", "ml", "unit",
    "units", "po", "iv", "daily", "bid", "tid", "qid", "prn", "oral", "qhs",
    "every", "hours", "hour", "day", "days", "times", "refills", "disp",
    "sig", "one", "two", "by", "mouth", "as", "needed", "for", "and", "the",
    "solution", "injection", "puff", "inhalation", "subcutaneous", "release",
    "extended", "delayed", "patch", "cream", "ointment", "drop", "drops",
}

MED_LINE = re.compile(r"^\s*\d+\s*[\.\)]\s*(.+)$")


def parseMedications(section: str | None) -> list[str]:
    """Pull drug names out of a numbered Discharge Medications section."""
    if not section:
        return []
    meds: list[str] = []
    for line in section.splitlines():
        match = MED_LINE.match(line)
        if not match:
            continue
        candidate = match.group(1)
        # drug name is whatever precedes the first dose figure
        candidate = re.split(r"\d", candidate)[0]
        candidate = re.sub(r"[^A-Za-z\s\-]", " ", candidate)
        tokens = [
            t for t in candidate.lower().split()
            if len(t) > 3 and t not in MED_NOISE
        ]
        if tokens:
            meds.append(tokens[0])
    return sorted(set(meds))


def parseAllergies(section: str | None) -> list[str]:
    if not section:
        return []
    text = section.strip().lower()
    if "no known" in text or text in {"none", "nka", "nkda"}:
        return []
    parts = re.split(r"[,\n/]| and ", text)
    return sorted({p.strip() for p in parts if len(p.strip()) > 3})


STOPWORDS = {
    "unspecified", "other", "with", "without", "and", "the", "of", "in", "not",
    "elsewhere", "classified", "due", "to", "type", "acute", "chronic",
    "disease", "disorder", "syndrome", "history", "personal", "status",
}


def diagnosisKeywords(title: str) -> set[str]:
    words = re.sub(r"[^a-z\s]", " ", title.lower()).split()
    return {w for w in words if len(w) > 4 and w not in STOPWORDS}


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9\s]", " ", text.lower())


def medPresent(med: str, output: str) -> bool:
    """Prefix match, so 'metoprolol' catches 'Metoprolol Succinate'."""
    stem = med[: max(5, len(med) - 2)]
    return stem in output


def diagnosisPresent(title: str, output: str) -> bool:
    keywords = diagnosisKeywords(title)
    if not keywords:
        return False
    hits = sum(1 for k in keywords if k[:6] in output)
    return hits / len(keywords) >= 0.5


HIGH_RISK_STEMS = (
    "warfarin", "apixaban", "rivaroxaban", "dabigatran", "enoxaparin",
    "heparin", "clopidogrel", "ticagrelor", "prasugrel", "insulin",
    "metformin", "glipizide", "glyburide", "digoxin", "amiodarone",
    "methotrexate", "prednisone", "levothyroxine",
)


def criticalItems(meds: list[str], allergies: list[str]) -> list[str]:
    critical = [m for m in meds if any(m.startswith(s[:6]) for s in HIGH_RISK_STEMS)]
    return critical + allergies


def generate(record: str) -> str:
    payload = {
        "model": MODEL,
        "prompt": PROMPT.format(record=record[:MAX_INPUT_CHARS]),
        "stream": False,
        "options": {"temperature": TEMPERATURE, "num_predict": 900},
    }
    response = requests.post(OLLAMA_URL, json=payload, timeout=600)
    response.raise_for_status()
    return response.json()["response"].strip()


@dataclass
class Score:
    hadmId: int
    medTotal: int
    medFound: int
    medRecall: float
    dxTotal: int
    dxFound: int
    dxRecall: float
    allergyTotal: int
    allergyFound: int
    criticalTotal: int
    criticalOmissions: int
    missingMeds: list[str]
    missingCritical: list[str]
    compressionRatio: float
    fkGrade: float
    outputChars: int


def score(row: dict, output: str) -> Score:
    flat = normalize(output)

    meds = parseMedications(row.get("dischargeMedsSection"))
    allergies = parseAllergies(row.get("allergiesSection"))
    diagnoses = row.get("dischargeDiagnoses") or []

    missingMeds = [m for m in meds if not medPresent(m, flat)]
    foundDx = [d for d in diagnoses if diagnosisPresent(d, flat)]
    foundAllergies = [a for a in allergies if a[:6] in flat]

    critical = criticalItems(meds, allergies)
    missingCritical = [
        c for c in critical
        if not (medPresent(c, flat) or c[:6] in flat)
    ]

    inputChars = max(1, int(row.get("inputChars") or len(row["modelInput"])))

    return Score(
        hadmId=int(row["hadm_id"]),
        medTotal=len(meds),
        medFound=len(meds) - len(missingMeds),
        medRecall=(len(meds) - len(missingMeds)) / len(meds) if meds else 1.0,
        dxTotal=len(diagnoses),
        dxFound=len(foundDx),
        dxRecall=len(foundDx) / len(diagnoses) if diagnoses else 1.0,
        allergyTotal=len(allergies),
        allergyFound=len(foundAllergies),
        criticalTotal=len(critical),
        criticalOmissions=len(missingCritical),
        missingMeds=missingMeds,
        missingCritical=missingCritical,
        compressionRatio=len(output) / inputChars,
        fkGrade=round(textstat.flesch_kincaid_grade(output), 2) if output else 0.0,
        outputChars=len(output),
    )


def report(scores: list[Score]) -> None:
    if not scores:
        print("no results")
        return

    def mean(field: str) -> float:
        return statistics.mean(getattr(s, field) for s in scores)

    withCritical = [s for s in scores if s.criticalTotal > 0]
    clean = sum(1 for s in withCritical if s.criticalOmissions == 0)

    print("\n" + "=" * 62)
    print(f"  FIRST PASS | {len(scores)} admissions | model {MODEL}")
    print("=" * 62)
    print(f"  medication recall        {mean('medRecall'):.3f}")
    print(f"  diagnosis recall         {mean('dxRecall'):.3f}")
    print(f"  compression ratio        {mean('compressionRatio'):.3f}")
    print(f"  output length (chars)    {mean('outputChars'):.0f}")
    print(f"  Flesch-Kincaid grade     {mean('fkGrade'):.1f}")
    print("-" * 62)
    print(f"  admissions with high-risk items    {len(withCritical)}")
    print(f"  of those, zero omissions           {clean}"
          f"  ({clean / len(withCritical):.1%})" if withCritical else "")
    print("=" * 62)

    worst = sorted(scores, key=lambda s: s.medRecall)[:5]
    print("\n  Lowest medication recall:")
    for s in worst:
        print(f"   hadm {s.hadmId}  {s.medRecall:.2f}  "
              f"({s.medFound}/{s.medTotal})  missing: "
              f"{', '.join(s.missingMeds[:6]) or 'none'}")

    offenders = [s for s in scores if s.criticalOmissions > 0]
    if offenders:
        print(f"\n  CRITICAL OMISSIONS in {len(offenders)} admissions:")
        for s in offenders[:10]:
            print(f"   hadm {s.hadmId}  missing: {', '.join(s.missingCritical)}")
    else:
        print("\n  No critical omissions detected.")


def loadRows(path: Path) -> list[dict]:
    raw = path.read_text(encoding="utf-8")
    if raw.lstrip().startswith("["):
        return json.loads(raw)
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="JSON export from the cohort query")
    parser.add_argument("--n", type=int, default=25)
    parser.add_argument("--out", default="firstPassResults.json")
    args = parser.parse_args()

    rows = loadRows(Path(args.input))[: args.n]
    print(f"loaded {len(rows)} admissions")

    # Fail loudly rather than silently reporting meaningless numbers.
    for row in rows:
        if "Discharge Instructions:" in row["modelInput"]:
            sys.exit(f"LEAK: hadm {row['hadm_id']} still contains the target section")
    print("leak check passed\n")

    scores: list[Score] = []
    outputs: list[dict] = []

    for i, row in enumerate(rows, 1):
        print(f"[{i}/{len(rows)}] hadm {row['hadm_id']} ... ", end="", flush=True)
        try:
            output = generate(row["modelInput"])
        except Exception as exc:                       # noqa: BLE001
            print(f"failed: {exc}")
            continue
        s = score(row, output)
        scores.append(s)
        outputs.append({
            "hadmId": s.hadmId,
            "generated": output,
            "reference": row.get("refInstructions"),
            "score": asdict(s),
        })
        print(f"medRecall {s.medRecall:.2f}  fk {s.fkGrade:.1f}")

    Path(args.out).write_text(json.dumps(outputs, indent=2), encoding="utf-8")
    report(scores)
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()