"""Generate patient discharge instructions from MIMIC-IV notes and score them.

modes: allText, structured, templated, sectional (or both / all)

    python scripts/runPass2.py --input D:/MIMIC-IV/cohortV2.json --n 100 --mode all
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path

import requests

try:
    import textstat
    HAVE_TEXTSTAT = True
except ImportError:
    HAVE_TEXTSTAT = False

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "medgemma"
TEMPERATURE = 0.0
# ollama defaults to a small context and silently cuts the front of long prompts
NUM_CTX = 16384
CHARS_PER_TOKEN = 3.2          # conservative for clinical text
MAX_INPUT_CHARS = 24000
MAX_HEADER_CHARS = 9000      # cap on the facts block
MIN_NARRATIVE_CHARS = 6000   # narrative floor, so the model always has context
MIN_OUTPUT_CHARS = 400       # below this the generation failed, do not score it

PROMPT = """You are writing the discharge instructions a patient will take home.

Use ONLY the information in the record below. Do not add advice, diagnoses, or
medications that do not appear in it.

You MUST include:
- Every medication in the discharge medication list, and why it is taken.
- Every allergy listed.
- What happened during this hospital stay, briefly.
- What to do over the next few days.
- What to watch for and when to seek help.
- Follow-up: who to contact and when.

Address the patient as "you". List every medication individually by name, one
per line, with what it is for. Do not summarize the medications as a group.

Do not include a patient name, date of birth, medical record number, or any
blank field to be filled in. Begin with what happened during the stay.

RECORD:
{record}

INSTRUCTIONS TO THE PATIENT:"""

TEMPLATED_PROMPT = """You are writing part of the discharge instructions a patient will take home.

The patient's medication list and allergies will be added separately, word for
word from the record. Do NOT list medications or allergies yourself.

Using ONLY the record below, write these four short sections, addressed to the
patient as "you":

What happened in the hospital:
What to do over the next few days:
When to get help right away:
Your follow-up:

Plain language. No title, no patient name, no date of birth, no blank fields.
Do not describe the record or say what it contains. Write to the patient.

RECORD:
{record}

"""


# record goes before the per-section part so ollama can reuse the cached prefix
SECTION_PROMPT = """You are writing discharge instructions a patient will take home.

Use ONLY the information in the record below. Do not add diagnoses, possible
causes, tests, or advice that do not appear in it. Do not speculate. Address
the patient as "you". Use plain, everyday language.

RECORD:
{record}

Write ONLY the section below. Do not write any other section. Do not list
medications or allergies; those are added separately.

Section: {header}
{instruction}"""

SECTIONS = (
    ("What happened in the hospital:",
     "In a few sentences, tell the patient why they came to the hospital and what was done."),
    ("What to do over the next few days:",
     "Tell the patient what to do at home over the next few days."),
    ("When to get help right away:",
     "Tell the patient which warning signs mean they should get help right away."),
    ("Your follow-up:",
     "Tell the patient about their follow-up appointments and who to contact."),
)


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

# lines that aren't medication entries
MED_REJECT = re.compile(r"^(none|no |n/a|see |per |same)", re.IGNORECASE)

MED_LINE = re.compile(r"^\s*\d+\s*[\.\)]\s*(.+)$")


def parseMedications(section: str | None) -> list[str]:
    if not section:
        return []
    meds: list[str] = []
    for line in section.splitlines():
        match = MED_LINE.match(line)
        if not match:
            continue
        candidate = match.group(1)
        candidate = MED_PREFIX.sub("", candidate)        # drop "Held- ", "Continue "
        if MED_REJECT.match(candidate):
            continue
        candidate = re.split(r"\d", candidate)[0]        # drug name precedes the dose
        candidate = re.sub(r"[^A-Za-z\s\-]", " ", candidate)

        tokens = candidate.lower().split()
        # first real word only, otherwise "Ferrous Sulfate" becomes "sulfate"
        head = next((t for t in tokens if len(t) > 2), None)
        if head is None or head in MED_NOISE or len(head) <= 3:
            continue
        meds.append(head)
    return sorted(set(meds))


def parseAllergies(section: str | None) -> list[str]:
    if not section:
        return []
    text = section.strip().lower()
    if "no known" in text or text in {"none", "nka", "nkda", ""}:
        return []
    parts = re.split(r"[,\n/;]| and ", text)
    cleaned = []
    for p in parts:
        p = re.sub(r"\(.*?\)", "", p)                 # drop parentheticals
        p = re.sub(r"[^a-z\s\-]", " ", p).strip()
        if len(p) > 3 and "___" not in p:
            cleaned.append(p.split()[0])              # first word is the agent
    return sorted(set(cleaned))


# meds where leaving one out can cause immediate harm
HIGH_RISK_STEMS = (
    "warfarin", "apixaban", "rivaroxaban", "dabigatran", "enoxaparin",
    "heparin", "clopidogrel", "ticagrelor", "prasugrel", "insulin",
    "metformin", "glipizide", "glyburide", "digoxin", "amiodarone",
    "methotrexate", "prednisone", "levothyroxine", "lithium", "phenytoin",
)


def isHighRisk(med: str) -> bool:
    return any(med.startswith(stem[:6]) for stem in HIGH_RISK_STEMS)


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9\s]", " ", text.lower())


def present(term: str, flat: str) -> bool:
    """Stem match on the first word of the drug name."""
    words = normalize(term).split()
    if not words:
        return False
    head = words[0]
    stem = head[: max(5, len(head) - 2)]
    return stem in flat


PLACEHOLDER_RUN = re.compile(r"_{2,}")
EMPTY_BRACKET = re.compile(r"[\(\[]\s*\[redacted\]\s*[\)\]]")
EXTRA_SPACE = re.compile(r"[ \t]{2,}")
BLANK_LINES = re.compile(r"\n{3,}")


def stripPlaceholders(text: str | None) -> str:
    """Collapse MIMIC's de-id underscores into one marker."""
    if not text:
        return ""
    text = PLACEHOLDER_RUN.sub("[redacted]", text)
    text = EMPTY_BRACKET.sub("", text)
    text = EXTRA_SPACE.sub(" ", text)
    return BLANK_LINES.sub("\n\n", text).strip()

def buildStructuredRecord(row: dict) -> str:
    """Facts first, then as much narrative as fits."""
    meds = parseMedications(row.get("dischargeMedsSection"))
    allergies = parseAllergies(row.get("allergiesSection"))
    diagnoses = (row.get("dischargeDiagnoses") or [])[:8]

    parts = ["=== DISCHARGE MEDICATIONS ==="]
    parts.append(stripPlaceholders(row.get("dischargeMedsSection")) or "none recorded")

    parts.append("\n=== ALLERGIES ===")
    parts.append(stripPlaceholders(row.get("allergiesSection")) or "No known allergies")

    if diagnoses:
        parts.append("\n=== DISCHARGE DIAGNOSES ===")
        parts.extend(f"- {d}" for d in diagnoses)

    if row.get("dispositionSection"):
        parts.append("\n=== DISCHARGE DISPOSITION ===")
        parts.append(stripPlaceholders(row["dispositionSection"]))

    header = "\n".join(parts)

    # cap the facts block so the narrative always has room
    if len(header) > MAX_HEADER_CHARS:
        header = header[:MAX_HEADER_CHARS] + "\n[...facts truncated...]"

    remaining = MAX_INPUT_CHARS - len(header) - 200
    narrative = stripPlaceholders(row["modelInput"])[:max(MIN_NARRATIVE_CHARS, remaining)]

    return f"{header}\n\n=== HOSPITAL RECORD ===\n{narrative}"


def buildAllTextRecord(row: dict) -> str:
    return stripPlaceholders(row["modelInput"])[:MAX_INPUT_CHARS]


PREAMBLE = re.compile(
    r"^\s*(okay|ok|sure|certainly|here (is|are)|i have|i've|based on)[^\n]*\n+",
    re.IGNORECASE,
)


def stripPreamble(text: str) -> str:
    """Strip chatbot openers like "Okay, here are..."."""
    previous = None
    while previous != text:
        previous = text
        text = PREAMBLE.sub("", text, count=1)
    return text.strip()


QUOTED_LINE = re.compile(r'^[ \t]*["\u201c\u201d](.*?)["\u201c\u201d][ \t]*$', re.MULTILINE)
END_OF_TURN = re.compile(r"<end_of_turn>.*$", re.DOTALL)


def cleanOutput(text: str) -> str:
    """Drop turn markers and stray quote marks."""
    text = END_OF_TURN.sub("", text)
    text = QUOTED_LINE.sub(r"\1", text)
    text = re.sub(r'["\u201c]\s*$|^\s*["\u201d]', "", text, flags=re.MULTILINE)
    return text.strip()


SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
SECOND_PERSON = re.compile(r"\b(you|your|you're|yours)\b", re.IGNORECASE)


REQUIRED_SECTIONS = (
    "what happened in the hospital",
    "what to do over the next",
    "when to get help",
    "your follow-up",
)


def sectionsPresent(text: str) -> int:
    lowered = (text or "").lower()
    return sum(1 for header in REQUIRED_SECTIONS if header in lowered)


def patientVoice(text: str) -> float:
    """Share of sentences addressed to the patient as "you"."""
    # skip header lines, they're the template not the writing
    body = "\n".join(
        line for line in (text or "").splitlines()
        if not any(h in line.lower() for h in REQUIRED_SECTIONS)
    )
    sentences = [x for x in SENTENCE.split(body) if len(x.split()) >= 4]
    if not sentences:
        return 0.0
    return sum(1 for x in sentences if SECOND_PERSON.search(x)) / len(sentences)


def renderMedications(section: str | None) -> str:
    """Copy the discharge med list as-is."""
    cleaned = stripPlaceholders(section)
    return cleaned if cleaned else "No medications were listed at discharge."


def renderAllergies(section: str | None) -> str:
    cleaned = stripPlaceholders(section)
    return cleaned if cleaned else "No known allergies."


def assembleTemplated(narrative: str, row: dict) -> str:
    return (
        f"{narrative.strip()}\n\n"
        f"YOUR MEDICATIONS\n{renderMedications(row.get('dischargeMedsSection'))}\n\n"
        f"YOUR ALLERGIES\n{renderAllergies(row.get('allergiesSection'))}"
    )


PREFILL_TEXT = "What happened in the hospital:\n"
TRUNCATION_WARNINGS: list[int] = []
PROMPT_TOKENS: list[int] = []


def generate(record: str, template: str | None = None,
             prefill: str | None = None, stop: list[str] | None = None,
             maxTokens: int = 900, formatArgs: dict | None = None) -> str:
    """Call ollama. With prefill, the model's reply starts with that text."""
    body = (template or PROMPT).format(record=record, **(formatArgs or {}))
    options = {"temperature": TEMPERATURE, "num_predict": maxTokens,
               "num_ctx": NUM_CTX}
    if stop:
        options["stop"] = stop
    payload = {"model": MODEL, "stream": False, "options": options}

    estimated = len(body) / CHARS_PER_TOKEN + maxTokens
    if estimated > NUM_CTX:
        TRUNCATION_WARNINGS.append(int(estimated))
    if prefill:
        payload["raw"] = True
        payload["prompt"] = (
            f"<start_of_turn>user\n{body}<end_of_turn>\n"
            f"<start_of_turn>model\n{prefill}"
        )
    else:
        payload["prompt"] = body

    response = requests.post(OLLAMA_URL, json=payload, timeout=900)
    response.raise_for_status()
    data = response.json()
    PROMPT_TOKENS.append(int(data.get("prompt_eval_count") or 0))
    text = data["response"]
    if prefill:
        text = prefill + text
    return cleanOutput(stripPreamble(text))


def generateSectional(record: str) -> str:
    """One call per section, each started inside its own header."""
    headerStems = [h.rstrip(":") for h, _ in SECTIONS]
    parts: list[str] = []
    for header, instruction in SECTIONS:
        others = [stem for stem in headerStems if stem != header.rstrip(":")]
        text = generate(
            record,
            SECTION_PROMPT,
            prefill=header + "\n",
            stop=others + ["<end_of_turn>", "YOUR MEDICATIONS", "Medications:"],
            maxTokens=320,
            formatArgs={"header": header, "instruction": instruction},
        )
        parts.append(text.strip())
    return "\n\n".join(parts)


@dataclass
class Score:
    hadmId: int
    mode: str
    inputChars: int
    outputChars: int
    compressionRatio: float
    medTotal: int
    medFound: int
    medRecall: float
    highRiskTotal: int
    highRiskMissing: int
    allergyTotal: int
    allergyFound: int
    allergyRecall: float
    fkGrade: float
    patientVoice: float = 0.0
    narrativeChars: int = 0
    sections: int = 0
    missingMeds: list[str] = field(default_factory=list)
    missingHighRisk: list[str] = field(default_factory=list)


def score(row: dict, output: str, mode: str, recordChars: int,
          narrative: str | None = None) -> Score:
    """Facts scored on the full doc, voice and FK on model-written text only."""
    flat = normalize(output)
    written = narrative if narrative is not None else output

    meds = parseMedications(row.get("dischargeMedsSection"))
    allergies = parseAllergies(row.get("allergiesSection"))

    missingMeds = [m for m in meds if not present(m, flat)]
    highRisk = [m for m in meds if isHighRisk(m)]
    missingHighRisk = [m for m in highRisk if not present(m, flat)]
    foundAllergies = [a for a in allergies if present(a, flat)]

    fk = 0.0
    if HAVE_TEXTSTAT and written:
        fk = round(textstat.flesch_kincaid_grade(written), 2)

    return Score(
        hadmId=int(row["hadm_id"]),
        mode=mode,
        inputChars=recordChars,
        outputChars=len(output),
        compressionRatio=len(output) / max(1, recordChars),
        medTotal=len(meds),
        medFound=len(meds) - len(missingMeds),
        medRecall=(len(meds) - len(missingMeds)) / len(meds) if meds else 1.0,
        highRiskTotal=len(highRisk),
        highRiskMissing=len(missingHighRisk),
        allergyTotal=len(allergies),
        allergyFound=len(foundAllergies),
        allergyRecall=len(foundAllergies) / len(allergies) if allergies else 1.0,
        fkGrade=fk,
        patientVoice=round(patientVoice(written), 3),
        narrativeChars=len(written),
        sections=sectionsPresent(written),
        missingMeds=missingMeds,
        missingHighRisk=missingHighRisk,
    )


def summarize(scores: list[Score], label: str) -> dict:
    if not scores:
        return {}
    withRisk = [s for s in scores if s.highRiskTotal > 0]
    perfect = sum(1 for s in scores if s.medRecall == 1.0)
    zero = sum(1 for s in scores if s.medRecall == 0.0)
    return {
        "mode": label,
        "n": len(scores),
        "medRecall": statistics.mean(s.medRecall for s in scores),
        "allergyRecall": statistics.mean(s.allergyRecall for s in scores),
        "perfect": perfect,
        "zero": zero,
        "highRiskClean": sum(1 for s in withRisk if s.highRiskMissing == 0),
        "highRiskN": len(withRisk),
        "compression": statistics.mean(s.compressionRatio for s in scores),
        "fkGrade": statistics.mean(s.fkGrade for s in scores),
        "voice": statistics.mean(s.patientVoice for s in scores),
        "adherent": sum(1 for s in scores if s.sections == len(REQUIRED_SECTIONS)),
    }


def report(rows: list[dict]) -> None:  # noqa: D103
    print("\n" + "=" * 92)
    print(f"  {'mode':<12}{'medRec':>8}{'allergy':>9}{'1.00':>7}{'0.00':>7}"
          f"{'hiRisk ok':>12}{'compress':>10}{'FK':>7}{'voice':>8}{'4/4 sec':>9}")
    print("-" * 92)
    for r in rows:
        if not r:
            continue
        risk = f"{r['highRiskClean']}/{r['highRiskN']}"
        print(f"  {r['mode']:<12}{r['medRecall']:>8.3f}{r['allergyRecall']:>9.3f}"
              f"{r['perfect']:>7}{r['zero']:>7}{risk:>12}"
              f"{r['compression']:>10.3f}{r['fkGrade']:>7.1f}{r['voice']:>8.2f}"
              f"{r['adherent']:>6}/{r['n']:<3}")
    print("=" * 92)
    print("  voice = share of sentences addressed to the patient as \"you\"")
    print("  FK and voice are measured on model-written text only")


LEAK_SHINGLE = 8


def shingles(text: str, n: int = LEAK_SHINGLE) -> set[str]:
    words = (text or "").split()
    return {" ".join(words[i:i + n]) for i in range(max(0, len(words) - n + 1))}


def leaks(row: dict) -> bool:
    """True if any 8-word run from the answer key shows up in the input."""
    ref = row.get("refInstructions") or ""
    if not ref:
        return False
    inputText = " ".join((row.get("modelInput") or "").split())
    return any(sh in inputText for sh in shingles(" ".join(ref.split())))


def loadRows(path: Path) -> list[dict]:
    raw = path.read_text(encoding="utf-8")
    if raw.lstrip().startswith("["):
        return json.loads(raw)
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


def runMode(rows: list[dict], mode: str,
            prefill: bool = False) -> tuple[list[Score], list[dict], list[dict]]:
    build = buildAllTextRecord if mode == "allText" else buildStructuredRecord
    templated = mode in ("templated", "sectional")
    sectional = mode == "sectional"
    scores: list[Score] = []
    outputs: list[dict] = []
    failures: list[dict] = []
    for i, row in enumerate(rows, 1):
        record = build(row)
        print(f"  [{i}/{len(rows)}] hadm {row['hadm_id']} ... ", end="", flush=True)
        try:
            if sectional:
                written = generateSectional(record)
            else:
                written = generate(
                    record,
                    TEMPLATED_PROMPT if templated else None,
                    PREFILL_TEXT if (prefill and templated) else None,
                )
        except Exception as exc:                      # noqa: BLE001
            print(f"failed: {exc}")
            continue
        output = assembleTemplated(written, row) if templated else written
        narrative = written if templated else None
        if len(written) < MIN_OUTPUT_CHARS:
            print(f"GENERATION FAILED ({len(written)} chars, not scored)")
            failures.append({"hadmId": int(row["hadm_id"]), "mode": mode,
                             "chars": len(written), "generated": written})
            continue
        s = score(row, output, mode, len(record), narrative)
        scores.append(s)
        outputs.append({
            "hadmId": s.hadmId, "mode": mode,
            "generated": output, "reference": row.get("refInstructions"),
            "score": asdict(s),
        })
        print(f"medRecall {s.medRecall:.2f}  ({s.medFound}/{s.medTotal})  "
              f"voice {s.patientVoice:.2f}  sections {s.sections}/4")
    return scores, outputs, failures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--n", type=int, default=25)
    parser.add_argument("--mode",
                        choices=["allText", "structured", "templated", "sectional",
                                 "both", "all"],
                        default="both")
    parser.add_argument("--out", default="pass2Results.json")
    parser.add_argument("--model", default=None,
                        help="override MODEL, e.g. gemma3:4b or medgemma")
    parser.add_argument("--prefill", action="store_true",
                        help="start the templated response inside the first section")
    args = parser.parse_args()

    global MODEL
    if args.model:
        MODEL = args.model
    print(f"model {MODEL}  temperature {TEMPERATURE}  context {NUM_CTX}  "
          f"prefill {'on' if args.prefill else 'off'}")

    allRows = loadRows(Path(args.input))
    clean, leaked = [], []
    for row in allRows:
        if leaks(row):
            leaked.append(str(row["hadm_id"]))
        else:
            clean.append(row)

    if leaked:
        print(f"LEAK CHECK: excluded {len(leaked)} of {len(allRows)} admissions "
              f"where answer-key text appears in the model input")
        print(f"  {', '.join(leaked[:12])}{' ...' if len(leaked) > 12 else ''}")
    else:
        print(f"LEAK CHECK: 0 of {len(allRows)} admissions leak")

    rows = clean[: args.n]
    print(f"running on {len(rows)} clean admissions")

    modes = {
        "both": ["allText", "structured"],
        "all": ["allText", "structured", "templated"],
    }.get(args.mode, [args.mode])
    allOutputs: list[dict] = []
    allFailures: list[dict] = []
    summaries: list[dict] = []

    for mode in modes:
        print(f"\n--- {mode} ---")
        scores, outputs, failures = runMode(rows, mode, args.prefill)
        allOutputs.extend(outputs)
        allFailures.extend(failures)
        summaries.append(summarize(scores, mode))

    Path(args.out).write_text(json.dumps(allOutputs, indent=2), encoding="utf-8")
    report(summaries)
    if PROMPT_TOKENS:
        peak = max(PROMPT_TOKENS)
        print(f"\n  context window {NUM_CTX}, largest prompt evaluated {peak} tokens")
        if peak >= NUM_CTX - 64:
            print("  WARNING: prompts are hitting the context limit and being truncated")
    if TRUNCATION_WARNINGS:
        print(f"  WARNING: {len(TRUNCATION_WARNINGS)} prompts estimated larger than "
              f"the context window (max ~{max(TRUNCATION_WARNINGS)} tokens)")
    if allFailures:
        print(f"\n  {len(allFailures)} generation failures, excluded from scoring:")
        for f in allFailures:
            print(f"   hadm {f['hadmId']:<12} {f['mode']:<12} {f['chars']} chars")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()