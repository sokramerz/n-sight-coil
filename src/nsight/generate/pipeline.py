"""Turn one admission into patient discharge instructions.

Modes, in increasing order of safety:
    allText     the whole note, model writes everything
    structured  key facts first, model writes everything
    templated   model writes the narrative in one call; meds and allergies attached from the record
    sectional   one call per narrative section; meds and allergies attached from the record

In templated and sectional mode the medication list is never generated, and by
default the model never sees it either, so it can't restate it wrongly.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from nsight.config import Settings
from nsight.evaluate.metrics import (READING_TARGET, ACTION_ITEMS, BOILERPLATE, Score, cleanOutput, properNouns,
                                     instructionItems, inventedDays, speculativeSentences, dedupe, isHeaderLine,
                                     numberTokens, readingGrade, score, stripDosing)
from nsight.generate.glossary import explainSections
from nsight.generate.extract import (FOLLOWUP, HAPPENED, HELP, MIN_UNITS, TODO, followupLines,
                                     renderSection, sortInstructions, unitCount, units)
from nsight.generate.model_client import OllamaClient
from nsight.generate.redflags import warningSigns
from nsight.generate.prompts import (ALL_TEXT_PROMPT, CHART_SECTIONS, INSTRUCTION_RULE,
                                     SECTION_HEADERS, SECTION_PROMPT,
                                     SECTIONS, SIMPLIFY_LINES_PROMPT, SIMPLIFY_PROMPT, TEMPLATED_PROMPT)
from nsight.ingest.cleaning import stripPlaceholders
from nsight.ingest.medications import (MedicationEntry, allergyLines, parseAllergies, renderOrders,
                                       parseMedicationEntries, parseMedications)
from nsight.ingest.segmentation import removeSections

MODES = ("allText", "structured", "templated", "sectional")
NARRATIVE_MODES = ("templated", "sectional")
MED_SECTIONS = ("Discharge Medications", "Medications on Admission")

MAX_INPUT_CHARS = 24000
MAX_HEADER_CHARS = 9000
MIN_NARRATIVE_CHARS = 6000
MIN_OUTPUT_CHARS = 400
SECTION_MAX_TOKENS = 320


class GenerationFailed(RuntimeError):
    pass


def buildAllText(record: dict) -> str:
    return stripPlaceholders(record.get("modelInput"))[:MAX_INPUT_CHARS]


def doctorInstructions(record: dict) -> str:
    """The clinician's patient instructions, unwrapped, with the letter greeting and sign-off removed."""
    paragraphs = units(stripPlaceholders(record.get("refInstructions")))
    # every unit goes out as a bullet so a second pass keeps it whole; without the marker a
    # doctor's bullet list reads as wrapped prose and runs into the line above it
    return "\n\n".join("\n".join(f"- {u}" for u in p) for p in paragraphs).strip()


def hasInstructions(record: dict) -> bool:
    return len(doctorInstructions(record)) >= 40


def buildStructured(record: dict, includeMedList: bool = True, includeInstructions: bool = False) -> str:
    """Key facts first, then as much of the note as fits."""
    parts: list[str] = []
    if includeInstructions and hasInstructions(record):
        parts += ["=== WHAT THE DOCTOR WROTE FOR THE PATIENT ===", doctorInstructions(record), ""]
    if includeMedList:
        parts += ["=== DISCHARGE MEDICATIONS ===",
                  stripPlaceholders(record.get("dischargeMedsSection")) or "none recorded", ""]
    parts += ["=== ALLERGIES ===",
              stripPlaceholders(record.get("allergiesSection")) or "No known allergies"]
    diagnoses = (record.get("dischargeDiagnoses") or [])[:8]
    if diagnoses:
        parts += ["", "=== DISCHARGE DIAGNOSES ==="] + [f"- {d}" for d in diagnoses]
    if record.get("dispositionSection"):
        parts += ["", "=== DISCHARGE DISPOSITION ===", stripPlaceholders(record["dispositionSection"])]
    orders = renderOrders(record.get("dischargeMedsSection"))
    if orders and not includeMedList:
        parts += ["", "=== TESTS AND SUPPLIES ORDERED ===", orders]

    header = "\n".join(parts)
    if len(header) > MAX_HEADER_CHARS:
        header = header[:MAX_HEADER_CHARS] + "\n[...facts truncated...]"

    note = record.get("modelInput") or ""
    if not includeMedList:
        note = removeSections(note, MED_SECTIONS)
    room = max(MIN_NARRATIVE_CHARS, MAX_INPUT_CHARS - len(header) - 200)
    return f"{header}\n\n=== HOSPITAL RECORD ===\n{stripPlaceholders(note)[:room]}"


def splitSections(narrative: str) -> list[dict]:
    """Split model text into the four patient sections. Text before any header is kept."""
    sections: list[dict] = []
    current = {"header": None, "body": []}
    for line in (narrative or "").splitlines():
        if isHeaderLine(line):
            if current["header"] or any(x.strip() for x in current["body"]):
                sections.append(current)
            flat = line.strip(" *#:").lower()
            header = next(h for h in SECTION_HEADERS if flat.startswith(h.lower()))
            rest = line.strip(" *#").split(":", 1)
            current = {"header": header, "body": [rest[1].strip()] if len(rest) > 1 and rest[1].strip() else []}
        else:
            current["body"].append(line)
    if current["header"] or any(x.strip() for x in current["body"]):
        sections.append(current)
    return [{"header": s["header"], "text": "\n".join(s["body"]).strip()} for s in sections]


@dataclass
class GenerationResult:
    mode: str
    model: str
    includeMedList: bool
    raw: str
    narrative: str
    sections: list[dict]
    medications: list[MedicationEntry]
    allergies: list[str]
    document: str
    score: Score
    dosingSentencesRemoved: int = 0
    promptTokens: int = 0
    durationMs: int = 0
    warnings: list[str] = field(default_factory=list)


def assembleDocument(narrative: str, medications: list[MedicationEntry],
                     allergies: list[str]) -> str:
    meds = "\n".join(f"{m.index}. {m.plain}" for m in medications if m.kind == "med") or \
        "No medications were listed at discharge."
    orders = "\n".join(f"- {m.plain}" for m in medications if m.kind == "order")
    allergyText = "\n".join(allergies) or "No known allergies."
    extra = f"\n\nTESTS AND SUPPLIES ORDERED FOR YOU\n{orders}" if orders else ""
    return f"{narrative.strip()}\n\nYOUR MEDICATIONS\n{meds}{extra}\n\nYOUR ALLERGIES\n{allergyText}"


def finalize(record: dict, mode: str, model: str, raw: str, includeMedList: bool,
             promptTokens: int = 0, durationMs: int = 0, settings: Settings | None = None,
             loopSource: str | None = None, withInstructions: bool = False,
             stripMedDosing: bool = True) -> GenerationResult:
    """Clean the raw output, attach facts for narrative modes, and score it.

    Shared by live generation and by importing earlier experiment results, so both
    go through exactly the same cleanup.
    """
    warnings: list[str] = []
    model = model.removesuffix(":latest")
    narrative = dedupe(cleanOutput(raw))
    medications = parseMedicationEntries(record.get("dischargeMedsSection"))
    allergies = allergyLines(record.get("allergiesSection"))
    removed = 0

    if mode in NARRATIVE_MODES:
        if stripMedDosing:
            narrative, removed = stripDosing(narrative, parseMedications(record.get("dischargeMedsSection")))
        if removed:
            warnings.append(f"removed {removed} narrative sentence(s) that restated medication dosing")
        document = assembleDocument(narrative, medications, allergies)
    else:
        document = narrative

    if len(narrative) < MIN_OUTPUT_CHARS and stripMedDosing:
        warnings.append("narrative is unusually short; generation may have failed")
    if settings and promptTokens >= settings.numCtx - 64:
        warnings.append("prompt hit the context limit and was truncated")

    sc = score(record, document, narrative, loopSource if loopSource is not None else raw,
               withInstructions=withInstructions)
    if sc.degenerate:
        warnings.append("model output repeated itself; duplicates were removed")
    if sc.highRiskMissing:
        warnings.append("missing high-risk medication(s): " + ", ".join(sc.missingHighRisk))
    if sc.unsupportedNumbers:
        warnings.append("numbers or days not found in the record: " + ", ".join(sc.unsupportedNumbers))
    if sc.speculative:
        warnings.append(f"{sc.speculative} sentence(s) speculate about causes or further testing")
    if sc.conflicts:
        warnings.append("course length differs from the record: " + ", ".join(sc.conflicts))
    if sc.missedInstructions:
        warnings.append("not carried over from the doctor's instructions: " + ", ".join(sc.missedInstructions))

    return GenerationResult(
        mode=mode, model=model, includeMedList=includeMedList, raw=raw, narrative=narrative,
        sections=splitSections(narrative), medications=medications, allergies=allergies,
        document=document, score=sc, dosingSentencesRemoved=removed,
        promptTokens=promptTokens, durationMs=durationMs, warnings=warnings,
    )


MIN_KEPT_SHARE = 0.5
SIMPLIFY_RETRIES = 1


def protectedTerms(text: str, record: dict) -> set[str]:
    """Facts a rewrite must keep: numbers, this patient's drugs and allergens, proper nouns."""
    lowered = text.lower()
    names = parseMedications(record.get("dischargeMedsSection")) + parseAllergies(record.get("allergiesSection"))
    terms = {n for n in names if n[:5] in lowered}
    return terms | properNouns(text) | numberTokens(text)


ACRONYM = re.compile(r"\b[A-Z]{2,5}\b")
NOT_ACRONYMS = {"I", "OK", "AM", "PM"}
# plain words a rewrite may use in place of a common abbreviation, as the prompt asks it to
SPELLED_OUT = {
    "PCP": r"primary care|regular doctor|family doctor", "ED": r"emergency", "ER": r"emergency",
    "PO": r"by mouth|swallow", "BID": r"twice|two times", "TID": r"three times", "QID": r"four times",
    "PRN": r"as needed|if needed|when needed", "QD": r"once a day|every day|daily", "QHS": r"bedtime",
    "HS": r"bedtime", "SOB": r"breath", "CP": r"chest pain", "BP": r"blood pressure", "HR": r"heart rate",
    "MD": r"doctor", "RN": r"nurse", "NP": r"nurse", "VNA": r"nurse", "PT": r"physical therap",
    "OT": r"occupational therap", "SNF": r"nursing|rehab", "ICU": r"intensive care", "IV": r"vein",
    "GI": r"stomach|digestive|gut|bowel", "UTI": r"urin|bladder", "CHF": r"heart failure",
    "COPD": r"lung", "DVT": r"clot", "PE": r"clot", "MI": r"heart attack", "CAD": r"heart|arter",
    "AFIB": r"heart rhythm|irregular heart", "BM": r"bowel movement|stool", "PCN": r"penicillin",
    "OTC": r"over the counter|without a prescription", "CBC": r"blood (count|test)",
    "INR": r"blood (test|thinning|level)", "EGD": r"scope|endoscopy", "CXR": r"x-?ray",
}


def lostAcronyms(original: str, rewrite: str) -> list[str]:
    """Abbreviations the rewrite neither kept nor spelled out."""
    missing = set(ACRONYM.findall(original)) - set(ACRONYM.findall(rewrite)) - NOT_ACRONYMS
    return sorted(a for a in missing
                  if not (a in SPELLED_OUT and re.search(SPELLED_OUT[a], rewrite, re.IGNORECASE)))


def lostActions(original: str, rewrite: str) -> list[str]:
    """Tests, treatments and follow-ups (MRI, bloodwork, antibiotics...) the rewrite no longer mentions."""
    # spot items with the strict clinical wording, accept any plain-language way of keeping them
    lost = [label for label, strict, loose in ACTION_ITEMS
            if re.search(strict, original, re.IGNORECASE) and not re.search(loose, rewrite, re.IGNORECASE)]
    lost += lostAcronyms(original, rewrite)
    return lost


def rewriteProblems(original: str, rewrite: str, record: dict) -> tuple[list[str], list[str]]:
    """Facts the rewrite lost and numbers it made up."""
    added = sorted(numberTokens(rewrite) - numberTokens(original))
    flat = rewrite.lower()
    kept = numberTokens(rewrite)
    lost = sorted(t for t in protectedTerms(original, record)
                  if (t not in kept if any(c.isdigit() for c in t) else t[:5] not in flat))
    return lost + lostActions(original, rewrite), added


# explaining medical words in parentheses, as the prompt asks, adds length on its own
MAX_GROWTH = 2.0
# a condition split off from its action reads as an order on its own: "If you get a fever."
FRAGMENT = re.compile(r"(?:^|[.!?]\s+|\n\s*(?:-\s+)?)(?:if|when|unless|because)\b(?:[^,.!?\n]|\.\d)*[.!?]", re.IGNORECASE)
MISSPELLED = re.compile(r"\bpuss\b", re.IGNORECASE)
BABY_TALK = re.compile(r"\b(tummy|tummies|poop|pooping|pee|peeing|potty|owie)\b", re.IGNORECASE)
CALL_US = re.compile(r"\b(call|contact|tell|let) us\b", re.IGNORECASE)
BULLET_LINE = re.compile(r"^\s*(?:[-*\u2022]|\d+[.)])\s+", re.MULTILINE)


def addedContent(original: str, rewrite: str, record: dict) -> list[str]:
    """What a rewrite brought in that the original did not have.

    A small model asked to simplify a short paragraph can return thirty bullets of
    generic advice with a made-up doctor and date. None of that is allowed.
    """
    problems = []
    if len(rewrite) > MAX_GROWTH * len(original) + 80:
        problems.append("longer")
    # splitting a long sentence into two short bullets is fine; a pile of new advice is not
    if len(BULLET_LINE.findall(rewrite)) > 2 * unitCount(original) + 1:
        problems.append("new list items")
    source = original + " " + " ".join(str(record.get(k) or "") for k in
                                       ("modelInput", "refInstructions", "dischargeMedsSection"))
    if properNouns(rewrite) - properNouns(source) - {w.lower() for w in re.findall(r"[A-Za-z]+", source)}:
        problems.append("new names")
    if inventedDays(rewrite, source):
        problems.append("new dates")
    if len(BABY_TALK.findall(rewrite)) > len(BABY_TALK.findall(original)):
        problems.append("baby talk")
    if len(CALL_US.findall(rewrite)) > len(CALL_US.findall(original)):
        problems.append("call us")
    if len(FRAGMENT.findall(rewrite)) > len(FRAGMENT.findall(original)):
        problems.append("fragment")
    if MISSPELLED.search(rewrite) and not MISSPELLED.search(original):
        problems.append("misspelling")
    return problems


def lostKinds(original: str, rewrite: str, record: dict) -> list[str]:
    """Which kinds of fact a rewrite dropped, without the facts themselves."""
    lowered, flat, kept = original.lower(), rewrite.lower(), numberTokens(rewrite)
    drugs = {n for n in parseMedications(record.get("dischargeMedsSection")) if n[:5] in lowered}
    allergens = {n for n in parseAllergies(record.get("allergiesSection")) if n[:5] in lowered}
    kinds = []
    if numberTokens(original) - kept:
        kinds.append("lost number")
    if any(d[:5] not in flat for d in drugs):
        kinds.append("lost drug")
    if any(a[:5] not in flat for a in allergens):
        kinds.append("lost allergy")
    if any(n[:5] not in flat for n in properNouns(original) - drugs - allergens):
        kinds.append("lost name")
    kinds += [f"lost action item: {label}" for label, strict, loose in ACTION_ITEMS
              if re.search(strict, original, re.IGNORECASE) and not re.search(loose, rewrite, re.IGNORECASE)]
    if lostAcronyms(original, rewrite):
        kinds.append("lost abbreviation")
    return kinds


def rewriteReasons(original: str, rewrite: str, record: dict) -> list[str]:
    """Every check a rewrite fails, as category names safe to log."""
    reasons = lostKinds(original, rewrite, record)
    # the same items the coverage metric counts, so a used rewrite can never lower coverage
    if any(re.search(pattern, original, re.IGNORECASE) and not re.search(pattern, rewrite, re.IGNORECASE)
           for _, pattern in instructionItems(record)):
        reasons.append("lost doctor's item")
    if numberTokens(rewrite) - numberTokens(original):
        reasons.append("added number")
    if len(rewrite) < MIN_KEPT_SHARE * len(original):
        reasons.append("too short")
    reasons += addedContent(original, rewrite, record)
    if speculativeSentences(rewrite) > speculativeSentences(original):
        reasons.append("speculation")
    if not reasons:
        before, after = readingGrade(original), readingGrade(rewrite)
        if before is not None and after is not None and after >= before:
            reasons.append("not simpler")
    return reasons


def checkRewrite(original: str, rewrite: str, record: dict) -> str:
    """'ok', 'lostFact' (a safety problem worth reporting), or 'notSimpler' (just not useful).

    Adding a number counts as a lost fact too: rewriters invent placeholder phone
    numbers and appointment times ("555-1234", "9:00") that a patient could act on.
    """
    reasons = rewriteReasons(original, rewrite, record)
    if not reasons:
        return "ok"
    return "notSimpler" if reasons == ["not simpler"] else "lostFact"


def retryNote(original: str, rewrite: str, record: dict, verdict: str) -> str:
    """Tell the rewriter what its last attempt got wrong."""
    if verdict == "notSimpler":
        return "- Your last try was not easier to read. Use shorter sentences and simpler words.\n"
    lost, added = rewriteProblems(original, rewrite, record)
    note = ""
    if lost:
        note += "- Your last try left out facts. Keep these exactly: " + ", ".join(lost) + ".\n"
    if added:
        note += "- Your last try added numbers that are not in the text: " + ", ".join(added) + \
                ". Do not add any numbers, phone numbers, or times.\n"
    for problem in addedContent(original, rewrite, record):
        note += {"longer": "- Your last try was much longer. Keep it about the same length.\n",
                 "new list items": "- Your last try added new points. Only reword what is there.\n",
                 "new names": "- Your last try added names that are not in the text.\n",
                 "new dates": "- Your last try added days or dates that are not in the text.\n",
                 "baby talk": "- Use adult words like stomach, stool, and urine.\n",
                 "call us": "- Do not write 'call us'. Keep who to call as written.\n",
                 "fragment": "- Keep each 'if' together with what to do in the same sentence.\n",
                 "misspelling": "- Check spelling: pus, not puss.\n"}[problem]
    if speculativeSentences(rewrite) > speculativeSentences(original):
        note += "- Your last try added guesses (like 'may be' or 'likely'). Only say what the text says.\n"
    if not note:
        note = "- Your last try was too short. Keep every sentence's meaning.\n"
    return note


def rewriteOnce(text: str, record: dict, client: OllamaClient, model: str,
                reasons: dict[str, int]) -> tuple[str | None, str]:
    """Rewrite one piece of text, retrying once with feedback. Returns the rewrite (or None) and the verdict."""
    note, verdict = "", "lostFact"
    for _ in range(1 + SIMPLIFY_RETRIES):
        completion = client.complete(SIMPLIFY_PROMPT.format(text=text, note=note), model, maxTokens=400)
        rewrite = "\n".join(l for l in cleanOutput(completion.text).splitlines()
                            if not isHeaderLine(l)).strip()
        if not rewrite:
            reasons["empty"] = reasons.get("empty", 0) + 1
            continue
        for reason in rewriteReasons(text, rewrite, record):
            reasons[reason] = reasons.get(reason, 0) + 1
        verdict = checkRewrite(text, rewrite, record)
        if verdict == "ok":
            return rewrite, verdict
        note = retryNote(text, rewrite, record, verdict)
    return None, verdict


def needsRewrite(text: str) -> bool:
    grade = readingGrade(text)
    return len(text) >= 40 and not (grade is not None and grade <= READING_TARGET)


NUMBERED = re.compile(r"^\s*(\d+)[.)]\s+(.+)$")


def rewriteLines(lines: list[str], record: dict, client: OllamaClient, model: str,
                 reasons: dict[str, int]) -> tuple[dict[int, str], int]:
    """Rewrite bullets together as numbered lines, checking and accepting each line on its own.

    Sending the bullets one call each made the model pad every line with new advice;
    seen together, it rewords them. Returns accepted rewrites by index and how many
    lines were rejected for dropping or adding a fact.
    """
    done: dict[int, str] = {}
    pending = list(range(len(lines)))
    verdicts: dict[int, str] = {}
    note = ""
    for _ in range(1 + SIMPLIFY_RETRIES):
        if not pending:
            break
        numbered = "\n".join(f"{n}. {lines[i]}" for n, i in enumerate(pending, 1))
        completion = client.complete(SIMPLIFY_LINES_PROMPT.format(text=numbered, note=note), model,
                                     maxTokens=60 * len(pending) + 100)
        answers = {}
        for line in cleanOutput(completion.text).splitlines():
            match = NUMBERED.match(line)
            if match and match.group(1) not in answers:
                answers[match.group(1)] = match.group(2).strip()
        notes, stillPending = [], []
        for n, i in enumerate(pending, 1):
            rewrite = answers.get(str(n), "")
            if not rewrite:
                reasons["empty"] = reasons.get("empty", 0) + 1
                stillPending.append(i)
                continue
            for reason in rewriteReasons(lines[i], rewrite, record):
                reasons[reason] = reasons.get(reason, 0) + 1
            verdicts[i] = checkRewrite(lines[i], rewrite, record)
            if verdicts[i] == "ok":
                done[i] = rewrite
            else:
                stillPending.append(i)
                notes += [x for x in retryNote(lines[i], rewrite, record, verdicts[i]).splitlines()
                          if x not in notes]
        pending = stillPending
        note = "\n".join(notes) + "\n" if notes else ""
    return done, sum(1 for i in pending if verdicts.get(i) == "lostFact")


def simplifySections(sections: list[dict], record: dict, client: OllamaClient,
                     model: str, skip: tuple[str, ...] = ()) -> tuple[list[dict], int, int, dict[str, int]]:
    """Rewrite each section in plain language, retrying once with feedback when a check fails.

    Bulleted sections are rewritten as numbered lines and checked line by line, so a
    bullet that fails a check keeps the doctor's wording without costing the rest.
    Returns the sections, how many had at least one rewrite used, how many had every
    rewrite thrown out for dropping or adding a fact, and a count of every failed
    check across all attempts. Rewrites that just weren't simpler are discarded quietly.
    """
    out, accepted, lostFacts = [], 0, 0
    reasons: dict[str, int] = {}
    for section in sections:
        text = section["text"]
        # fixed text is already plain, and a section already at the target only risks damage
        if section["header"] in skip or not needsRewrite(text):
            out.append(section)
            continue
        lines = text.splitlines()
        if section["header"] == HAPPENED or not any(BULLET_LINE.match(l) for l in lines):
            rewrite, verdict = rewriteOnce(text, record, client, model, reasons)
            if rewrite is not None:
                out.append({**section, "text": rewrite})
                accepted += 1
            else:
                out.append(section)
                lostFacts += verdict == "lostFact"
            continue
        targets = [i for i, l in enumerate(lines)
                   if BULLET_LINE.match(l) and needsRewrite(BULLET_LINE.sub("", l))]
        done, lost = rewriteLines([BULLET_LINE.sub("", lines[i]).strip() for i in targets],
                                  record, client, model, reasons)
        kept = list(lines)
        for k, rewrite in done.items():
            kept[targets[k]] = f"- {rewrite}"
        used = len(done)
        out.append({**section, "text": "\n".join(kept)} if used else section)
        accepted += used > 0
        lostFacts += not used and lost > 0
    return out, accepted, lostFacts, reasons


def joinSections(sections: list[dict]) -> str:
    return "\n\n".join(f"{s['header']}:\n{s['text']}" if s["header"] else s["text"] for s in sections)


MAX_BULLETS = 8
HAPPENED_MAX_TOKENS = 160


def capBullets(text: str) -> str:
    """Keep each generated section short: at most 8 bullets, no runs of same-opening bullets.

    A 4B model can slide into "You may experience X. You may experience Y..." for dozens of lines.
    """
    out, count, openings = [], 0, {}
    for line in text.splitlines():
        if isHeaderLine(line):
            out.append(line)
            count, openings = 0, {}
            continue
        if re.match(r"^\s*(?:[-*\u2022]|\d+[.)])\s+", line):
            words = re.findall(r"[a-z']+", line.lower())
            opening = " ".join(words[:3])
            openings[opening] = openings.get(opening, 0) + 1
            if count >= MAX_BULLETS or len(words) < 3 or openings[opening] > 2:
                continue
            count += 1
        out.append(line)
    return "\n".join(out)


def writeSection(client: OllamaClient, model: str, context: str, header: str, instruction: str,
                 useInstructions: bool):
    """One model call for one section."""
    others = [h for h in SECTION_HEADERS if h != header]
    stop = others + ["<end_of_turn>", "YOUR MEDICATIONS", "Medications:"]
    maxTokens = SECTION_MAX_TOKENS
    if header == HAPPENED:
        # a paragraph, so stop at the first blank line or list item
        stop += ["\n\n", "\n*", "\n-", "\n\u2022"]
        maxTokens = HAPPENED_MAX_TOKENS
    prompt = SECTION_PROMPT.format(record=context, header=header + ":", instruction=instruction,
                                   sourceRule=INSTRUCTION_RULE if useInstructions else "")
    out = client.complete(prompt, model, prefill=header + ":\n", stop=stop, maxTokens=maxTokens)
    text = cleanOutput(out.text)
    if header == HAPPENED:
        body = [re.sub(r"^\s*(?:[-*\u2022]|\d+[.)])\s+", "", l) for l in text.splitlines()[1:]]
        text = f"{header}:\n" + " ".join(l.strip() for l in body if l.strip())
    return text, out.promptTokens


NO_FOLLOWUP = "No follow-up visits were listed. Call your regular doctor to ask when you should be seen."
ALWAYS_TODO = "Take your medicines exactly as shown in the medicine list below."
HOME_SERVICE = "A home health nurse will visit you at home."


def extractNarrative(record: dict) -> tuple[str, list[str]] | None:
    """Build every section from the record itself, with no model writing.

    The doctor's own sentences come first. A section the doctor left empty is filled from
    another part of the record (the note's follow-up section, the discharge diagnoses) or
    from fixed text that is true for every patient. Returns the text and which sections
    used a fallback, or None when the doctor wrote too little to start from.
    """
    text = doctorInstructions(record)
    if unitCount(text) < MIN_UNITS:
        return None
    sections = sortInstructions(text)
    filled: list[str] = []

    existing = " ".join(sections[FOLLOWUP] + sections[TODO]).lower()
    for line in followupLines(record.get("modelInput")):
        line = stripPlaceholders(line)
        words = [w for w in re.findall(r"[a-z]+", line.lower())
                 if w not in {"dr", "the", "with", "appointment", "redacted", "md", "np"}]
        # skip an appointment the doctor already described, unless the note adds its time
        if words and re.search(rf"\b{words[0]}\b", existing) and not re.search(r"\d", line):
            continue
        sections[FOLLOWUP].append(f"Appointment: {line}")
    if not sections[FOLLOWUP]:
        sections[FOLLOWUP] = [NO_FOLLOWUP]
        filled.append(FOLLOWUP)

    if not sections[HELP]:
        sections[HELP] = warningSigns(record.get("dischargeDiagnoses") or [],
                                      record.get("dischargeMedsSection"))
        filled.append(HELP)

    if not sections[TODO]:
        sections[TODO] = [ALWAYS_TODO]
        if "service" in (record.get("dispositionSection") or "").lower():
            sections[TODO].append(HOME_SERVICE)
        filled.append(TODO)

    if not sections[HAPPENED]:
        diagnoses = [d for d in (record.get("dischargeDiagnoses") or [])[:4] if d.strip()]
        sections[HAPPENED] = ["You were treated in the hospital for: " + "; ".join(diagnoses) + "."] \
            if diagnoses else ["You were treated in the hospital."]
        filled.append(HAPPENED)

    parts = [f"{h}:\n{renderSection(h, sections[h])}" for h in SECTION_HEADERS]
    return "\n\n".join(parts), filled


def generateDocument(record: dict, client: OllamaClient, *, mode: str = "sectional",
                     model: str | None = None, includeMedList: bool | None = None,
                     simplify: bool = False, simplifyModel: str | None = None,
                     useInstructions: bool = True, generative: bool = False) -> GenerationResult:
    if mode not in MODES:
        raise ValueError(f"unknown mode '{mode}', expected one of {', '.join(MODES)}")
    settings = client.settings
    model = client.resolveModel(model or settings.model)
    if includeMedList is None:
        includeMedList = mode not in NARRATIVE_MODES
    # only the sectional prompts know how to use the doctor's text
    useInstructions = useInstructions and mode == "sectional" and hasInstructions(record)

    started = time.monotonic()
    promptTokens = 0
    strategy = "generate"
    filledSections: list[str] = []
    if mode == "allText":
        prompt = ALL_TEXT_PROMPT.format(record=buildAllText(record))
        out = client.complete(prompt, model)
        raw, promptTokens = out.text, out.promptTokens
    elif mode == "structured":
        prompt = ALL_TEXT_PROMPT.format(record=buildStructured(record, True))
        out = client.complete(prompt, model)
        raw, promptTokens = out.text, out.promptTokens
    elif mode == "templated":
        prompt = TEMPLATED_PROMPT.format(record=buildStructured(record, includeMedList))
        out = client.complete(prompt, model, maxTokens=600)
        raw, promptTokens = out.text, out.promptTokens
    else:
        extracted = None
        if useInstructions and not generative:
            extracted = extractNarrative(record)
        if extracted:
            raw, filledSections = extracted
            strategy = "extract"
        else:
            context = buildStructured(record, includeMedList, useInstructions)
            parts = []
            for header, instruction in (SECTIONS if useInstructions else CHART_SECTIONS):
                if header == HELP:
                    # the same fixed warning signs the sorted path uses, not model-written ones
                    signs = warningSigns(record.get("dischargeDiagnoses") or [], record.get("dischargeMedsSection"))
                    parts.append(f"{HELP}:\n{renderSection(HELP, signs)}")
                    filledSections.append(HELP)
                    continue
                written, tokens = writeSection(client, model, context, header, instruction, useInstructions)
                parts.append(written)
                promptTokens = max(promptTokens, tokens)
            raw = "\n\n".join(parts)

    loopSource = raw
    if strategy == "generate" and mode == "sectional":
        raw = capBullets(raw)
    result = finalize(record, mode, model, raw, includeMedList, promptTokens, 0, settings,
                      loopSource=loopSource, withInstructions=useInstructions,
                      stripMedDosing=strategy != "extract")
    if len(result.narrative) < 100:
        raise GenerationFailed("model returned almost no text")

    if simplify and mode in NARRATIVE_MODES:
        draftCoverage = result.score.instructionCoverage
        rewriter = client.resolveModel(simplifyModel) if simplifyModel else model
        sections, accepted, rejected, reasons = simplifySections(result.sections, record, client, rewriter,
                                                        skip=tuple(filledSections))
        result = finalize(record, mode, model, joinSections(sections), includeMedList,
                          promptTokens, 0, settings, loopSource=loopSource, withInstructions=useInstructions,
                          stripMedDosing=strategy != "extract")
        result.raw = raw
        result.score.draftCoverage = draftCoverage
        result.score.simplifiedSections = accepted
        result.score.simplifyRejected = rejected
        result.score.simplifyReasons = reasons
        if rejected:
            result.warnings.append(f"{rejected} simplified section(s) dropped or added a fact and were not used")

    explained: list[str] = []
    if mode in NARRATIVE_MODES:
        sections, explained = explainSections(result.sections)
        if explained:
            kept = result
            result = finalize(record, mode, model, joinSections(sections), includeMedList,
                              promptTokens, 0, settings, loopSource=loopSource, withInstructions=useInstructions,
                              stripMedDosing=strategy != "extract")
            result.raw = kept.raw
            for key in ("draftCoverage", "simplifiedSections", "simplifyRejected", "simplifyReasons"):
                setattr(result.score, key, getattr(kept.score, key))
            result.warnings += [w for w in kept.warnings if w not in result.warnings]

    result.score.strategy = strategy
    result.score.filledSections = filledSections
    result.score.explainedTerms = explained
    if HELP in filledSections:
        result.warnings.append("'When to get help' uses standard warning signs for the diagnoses, "
                               "not the doctor's note; needs clinician review")
    result.durationMs = int((time.monotonic() - started) * 1000)
    return result
