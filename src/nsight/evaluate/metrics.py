"""Output cleanup and scoring for generated discharge instructions."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from nsight.generate.prompts import SECTION_HEADERS
from nsight.ingest.medications import isHighRisk, parseAllergies, parseMedications

try:
    import textstat
    HAVE_TEXTSTAT = True
except ImportError:
    HAVE_TEXTSTAT = False

READING_TARGET = 6.0

# sentence ends, but not after a title: "see Dr. ___" is one sentence
SENTENCE_END = r"(?<!\b[A-Z]\.)(?<!\bDr\.)(?<!\bMr\.)(?<!\bMs\.)(?<!\bMrs\.)(?<!\bSt\.)(?<=[.!?])\s+"
SENTENCE = re.compile(SENTENCE_END + r"|\n+")
SECOND_PERSON = re.compile(r"\b(you|your|you're|yours)\b", re.IGNORECASE)
PREAMBLE = re.compile(
    r"^\s*(okay|ok|sure|certainly|here (is|are)|i have|i've|based on)[^\n]*\n+",
    re.IGNORECASE,
)
QUOTED_LINE = re.compile(r'^[ \t]*["“”](.*?)["“”][ \t]*$', re.MULTILINE)
END_OF_TURN = re.compile(r"<end_of_turn>.*$", re.DOTALL)
DOSING = re.compile(
    r"\b\d+(\.\d+)?\s*(mg|mcg|g|gram|grams|units?|ml|meq)\b"
    r"|\bby mouth\b|\b(po|bid|tid|qid|qhs|prn)\b"
    r"|\b(once|twice|three times|four times) (a|per) day\b"
    r"|\bevery \d+\s*(-\s*\d+\s*)?hours?\b",
    re.IGNORECASE,
)
# a line that only introduces a medication list, left dangling once the list is gone
LEAD_IN = re.compile(
    r"(following|these|your|the) (medications?|medicines?|prescriptions?)\b[^.!?]*:\s*$",
    re.IGNORECASE,
)


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())


def present(term: str, flat: str) -> bool:
    """Stem match on the first word of a drug or allergen name."""
    words = normalize(term).split()
    if not words:
        return False
    head = words[0]
    return head[: max(5, len(head) - 2)] in flat


def stripPreamble(text: str) -> str:
    previous = None
    while previous != text:
        previous = text
        text = PREAMBLE.sub("", text, count=1)
    return text.strip()


def cleanOutput(text: str) -> str:
    text = END_OF_TURN.sub("", text)
    text = QUOTED_LINE.sub(r"\1", text)
    text = re.sub(r'["“]\s*$|^\s*["”]', "", text, flags=re.MULTILINE)
    # one bullet style, whatever the model used
    text = re.sub(r"^[ \t]*[*\u2022][ \t]+", "- ", text, flags=re.MULTILINE)
    return stripPreamble(text.strip())


def sentenceKey(sentence: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", sentence.lower()).strip()


def repetition(text: str) -> tuple[float, int]:
    """Share of sentences that repeat an earlier one, and the worst repeat count."""
    keys = [sentenceKey(x) for x in SENTENCE.split(text or "") if len(x.split()) >= 4]
    if not keys:
        return 0.0, 0
    counts: dict[str, int] = {}
    for k in keys:
        counts[k] = counts.get(k, 0) + 1
    return (len(keys) - len(counts)) / len(keys), max(counts.values())


def isDegenerate(text: str) -> bool:
    rate, worst = repetition(text)
    return rate >= 0.25 or worst >= 3


def dedupe(text: str) -> str:
    """Drop repeated lines and sentences, keeping the first of each."""
    seenLines: set[str] = set()
    seenSentences: set[str] = set()
    kept: list[str] = []
    for line in (text or "").splitlines():
        lineKey = sentenceKey(line)
        if lineKey and len(line.split()) >= 4 and lineKey in seenLines:
            continue
        seenLines.add(lineKey)
        keep = []
        for part in re.split(SENTENCE_END, line):
            key = sentenceKey(part)
            if len(part.split()) >= 4 and key in seenSentences:
                continue
            seenSentences.add(key)
            keep.append(part)
        if keep or not line.strip():
            kept.append(" ".join(keep))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


def mentionsDosing(sentence: str, meds: list[str]) -> bool:
    if not DOSING.search(sentence):
        return False
    flat = normalize(sentence)
    return any(present(m, flat) for m in meds)


def medRestatements(narrative: str, meds: list[str]) -> int:
    """Narrative sentences that name a discharge drug and give dosing for it."""
    return sum(1 for s in SENTENCE.split(narrative or "") if mentionsDosing(s, meds))


def stripDosing(narrative: str, meds: list[str]) -> tuple[str, int]:
    """Remove narrative sentences that restate medication dosing.

    Dosing lives in the verbatim medication list. A second copy in the narrative
    can only add a chance to contradict it.
    """
    removed = 0
    kept: list[str] = []
    for line in (narrative or "").splitlines():
        if not line.strip():
            kept.append("")
            continue
        keep = []
        for part in re.split(SENTENCE_END, line):
            if mentionsDosing(part, meds):
                removed += 1
                continue
            keep.append(part)
        text = " ".join(keep).strip()
        if not text or re.fullmatch(r"[*\-\s]*", text) or LEAD_IN.search(text):
            continue
        kept.append(text)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip(), removed


# digits glued to letters still count: "27th", "10am"
NUMBER = re.compile(r"(?<![\w.])\d+(?:[.:/]\d+)*(?!\d)")
SPECULATION = re.compile(
    r"\b(could be|may be due|might be|may indicate|possibly|possible causes?|"
    r"likely (?:due|linked|related|caused|from)|probably (?:due|from|caused)|consider(?:ing)?|further (?:testing|evaluation|investigation|imaging)|"
    r"it is possible|potential(?:ly)? (?:cause|diagnos))",
    re.IGNORECASE,
)


ALWAYS_OK_NUMBERS = {"911"}


def numberTokens(text: str) -> set[str]:
    return set(NUMBER.findall(text or ""))


def unsupportedNumbers(narrative: str, source: str) -> list[str]:
    """Numbers the model wrote that appear nowhere in the record it was given.

    Catches invented doses, dates, lab values, and phone numbers. Small counting
    words like "1" or "2" are ignored since plain language uses them freely.
    """
    # also digits inside pharmacy codes, like the 12 in Q12H
    known = numberTokens(source) | set(re.findall(r"\d+(?:\.\d+)?", source or "")) | ALWAYS_OK_NUMBERS
    return sorted(n for n in numberTokens(narrative) - known if not re.fullmatch(r"[0-9]", n))


WEEKDAY_OR_MONTH = re.compile(
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|january|february|march|april|"
    r"june|july|august|september|october|november|december)\b", re.IGNORECASE)
NUMBER_WORDS = {w: str(i) for i, w in enumerate(
    ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
     "eleven", "twelve", "thirteen", "fourteen"))}
SPAN = re.compile(r"\b(\d+|" + "|".join(NUMBER_WORDS) + r")\s+(?:more\s+)?(day|week|month)s?\b", re.IGNORECASE)


def inventedDays(narrative: str, source: str) -> list[str]:
    """Weekdays and months the model wrote that the record never mentions ("see Dr. X on Monday")."""
    known = {w.lower() for w in WEEKDAY_OR_MONTH.findall(source or "")}
    return sorted({w.lower() for w in WEEKDAY_OR_MONTH.findall(narrative or "")} - known)


def spans(text: str) -> set[tuple[str, str]]:
    return {(NUMBER_WORDS.get(n.lower(), n), unit.lower()) for n, unit in SPAN.findall(text or "")}


def durationConflicts(narrative: str, record: dict, withInstructions: bool) -> list[str]:
    """A medicine's course length in the narrative that matches nothing the record says for it.

    "Take prednisone for 5 more days" when the medicine list says 2 days is a number the
    unsupported-number check cannot see, because 5 appears elsewhere in the record.
    """
    meds = parseMedications(record.get("dischargeMedsSection"))
    medLines = (record.get("dischargeMedsSection") or "").splitlines()
    refSentences = SENTENCE.split(record.get("refInstructions") or "") if withInstructions else []
    conflicts = []
    for sentence in SENTENCE.split(narrative or ""):
        said = spans(sentence)
        if not said:
            continue
        for med in meds:
            if med[:5] not in sentence.lower():
                continue
            allowed: set[tuple[str, str]] = set()
            for line in medLines + refSentences:
                if med[:5] in line.lower():
                    allowed |= spans(line.replace("Duration:", ""))
            if allowed and not said <= allowed:
                conflicts += [f"{med} {n} {u}s" for n, u in sorted(said - allowed)]
    return sorted(set(conflicts))


def speculativeSentences(narrative: str, doctorText: str = "") -> int:
    """Sentences that guess at causes or suggest workup the record doesn't contain.

    A sentence the doctor wrote word for word is the doctor's judgment, not a guess.
    """
    doctor = sentenceKey(" ".join(doctorText.split()))
    return sum(1 for s in SENTENCE.split(narrative or "")
               if SPECULATION.search(s) and not (doctor and sentenceKey(s) in doctor))


def isHeaderLine(line: str) -> bool:
    flat = line.strip(" *#:").lower()
    return any(flat.startswith(h.lower()) for h in SECTION_HEADERS)


def sectionsPresent(text: str) -> int:
    lowered = (text or "").lower()
    return sum(1 for h in SECTION_HEADERS if h.lower() in lowered)


def patientVoice(text: str) -> float:
    """Share of sentences addressed to the patient as "you". Header lines are skipped."""
    body = "\n".join(l for l in (text or "").splitlines() if not isHeaderLine(l))
    sentences = [x for x in SENTENCE.split(body) if len(x.split()) >= 4]
    if not sentences:
        return 0.0
    return sum(1 for x in sentences if SECOND_PERSON.search(x)) / len(sentences)


ABBREVIATION = re.compile(r"\b(?:[A-Z]{2,6}|[A-Z][a-z]?[A-Z]{1,4})s?\b")
NOT_JARGON = {"I", "A", "OK", "AM", "PM", "US", "TV", "ID", "Dr", "Mr", "Ms", "Mrs", "Rx"}
# doctors write these in capitals for emphasis ("STOP furosemide")
SHOUTED = {"stop", "start", "do", "not", "no", "yes", "call", "take", "hold", "new", "change", "changed",
           "continue", "increase", "decrease", "important", "only", "all", "and", "or", "if", "please",
           "before", "after", "until", "every", "daily", "never", "always", "note", "you", "your"}


def unexplainedAbbreviations(text: str) -> list[str]:
    """Abbreviations that are never followed by an explanation in parentheses."""
    explained, seen = set(), []
    for match in ABBREVIATION.finditer(text or ""):
        term = match.group(0)
        if term in NOT_JARGON or term.lower() in SHOUTED:
            continue
        if re.match(r"\s?\(", text[match.end():match.end() + 2]):
            explained.add(term)
        elif term not in seen:
            seen.append(term)
    return [t for t in seen if t not in explained]


def readability(text: str) -> dict[str, float | None]:
    """A readability suite, so no single formula decides the result.

    smog and daleChall are grade levels like Flesch-Kincaid; difficultWords is the
    share of words outside Dale-Chall's list of familiar words; jargon is distinct
    unexplained abbreviations per 100 words.
    """
    out: dict[str, float | None] = {"smog": None, "daleChall": None, "difficultWords": None, "jargon": None}
    text = (text or "").strip()
    if not text:
        return out
    words = len(re.findall(r"[A-Za-z]+", text))
    out["jargon"] = round(100 * len(unexplainedAbbreviations(text)) / words, 3) if words else None
    if not HAVE_TEXTSTAT:
        return out
    try:
        out["smog"] = round(textstat.smog_index(text), 2)
        out["daleChall"] = round(textstat.dale_chall_readability_score(text), 2)
        out["difficultWords"] = round(textstat.difficult_words(text) / words, 4) if words else None
    except Exception:  # noqa: BLE001
        pass
    return out


def readingGrade(text: str) -> float | None:
    """Flesch-Kincaid grade, or None if it can't be computed.

    textstat fetches a pronunciation dictionary through nltk on first use. If that
    isn't cached (run `python -m nltk.downloader cmudict` once), the score is
    skipped rather than failing the whole generation.
    """
    if not HAVE_TEXTSTAT or not (text or "").strip():
        return None
    try:
        return round(textstat.flesch_kincaid_grade(text), 2)
    except Exception:  # noqa: BLE001
        return None


PROPER_NOUN = re.compile(r"(?<![.!?:]\s)(?<!^)\b([A-Z][a-z]{2,})\b", re.MULTILINE)
COMMON_CAPS = {"You", "Your", "We", "Our", "The", "This", "If", "Please", "Call", "Take", "Monday",
               "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday", "Team",
               "Dear", "Sincerely", "Thank"}
LIST_MARKER = re.compile(r"^[ \t]*(?:[-*\u2022]|\d+[.)])[ \t]*", re.MULTILINE)
TITLE = re.compile(r"\b(Dr|Mr|Mrs|Ms)\.\s")


def properNouns(text: str) -> set[str]:
    """Capitalized words that look like names: not sentence or bullet openers, never lowercase elsewhere."""
    plain = TITLE.sub(r"\1 ", LIST_MARKER.sub("", text or ""))
    lowerWords = set(re.findall(r"\b[a-z]{3,}\b", plain))
    return {w.lower() for w in PROPER_NOUN.findall(plain)
            if w not in COMMON_CAPS and w.lower() not in lowerWords}


# ------------------------------------------------- doctor's instruction coverage

# letter boilerplate around the instructions, not something the patient has to do
BOILERPLATE = re.compile(
    r"^\s*(dear\b|it was (a|our) pleasure|we wish you|sincerely|thank you|best wishes|"
    r"your .{0,40}team\s*$|take care\b)", re.IGNORECASE)

# action items a patient document has to carry over, with plain-language equivalents.
# (label, how the doctor might say it, how a patient document might say it)
ACTION_ITEMS = (
    ("bloodwork", r"blood ?work|\blabs?\b|lab work|blood (test|draw|count)|draw blood|\bINR\b|\bCBC\b|\bchem\s?\d*\b|trough",
     r"blood ?work|\blabs?\b|lab work|blood (test|draw|count)|(draw|take|check)\w* (your |some )?blood|\bINR\b|\bCBC\b|trough"),
    ("antibiotics", r"antibiotic", r"antibiotic"),
    ("MRI", r"\bMRI\b", r"\bMRI\b|magnetic"),
    ("CT scan", r"\bCT\b|cat scan", r"\bCT\b|cat scan"),
    ("ultrasound", r"ultrasound", r"ultrasound"),
    ("x-ray", r"x-?ray|\bCXR\b", r"x-?ray"),
    ("echocardiogram", r"\becho(cardiogram)?\b|\bTTE\b|\bTEE\b", r"\becho(cardiogram)?\b|heart ultrasound"),
    ("colonoscopy/endoscopy", r"colonoscopy|endoscopy|\bEGD\b", r"colonoscopy|endoscopy|\bEGD\b|scope"),
    ("biopsy", r"biopsy", r"biopsy"),
    ("dialysis", r"dialysis|(?-i:\bHD\b)", r"dialysis"),
    ("line or port", r"\bPICC\b|\bport\b|central line|tunneled|\bline\b", r"\bPICC\b|\bport\b|\bline\b|tube"),
    ("catheter", r"catheter|foley", r"catheter|foley|tube"),
    ("drain", r"\bdrains?\b", r"\bdrains?\b"),
    ("wound care", r"wound|incision|dressing|stitches|sutures|staples", r"wound|incision|dressing|stitches|sutures|staples|cut"),
    ("daily weight", r"weigh", r"weigh"),
    ("diet", r"\bdiet\b|\bsalt\b|sodium|fluid restriction|restrict.{0,15}fluid|liters? of (fluid|water)",
     r"\bdiet\b|salt|sodium|fluid|drink"),
    ("avoid NSAIDs", r"\bNSAIDs?\b|ibuprofen|naproxen|advil|motrin|aleve", r"\bNSAIDs?\b|ibuprofen|naproxen|advil|motrin|aleve"),
    ("lifting limits", r"\blift", r"\blift"),
    ("driving", r"\bdriv", r"\bdriv"),
    ("bathing", r"shower|\bbath(e|es|ing|s)?\b", r"shower|\bbath|wash"),
    ("smoking", r"smok|tobacco|cigarette", r"smok|tobacco|cigarette"),
    ("alcohol", r"alcohol|drinking", r"alcohol"),
    ("oxygen", r"oxygen|\bO2\b", r"oxygen"),
    ("blood sugar", r"blood sugar|glucose|insulin|fingerstick", r"blood sugar|glucose|insulin"),
    ("physical therapy", r"physical therapy|(?-i:\bPT\b)|rehab", r"physical therapy|therapist|rehab|exercise"),
    ("visiting nurse", r"visiting nurse|\bVNA\b|home nurse|nursing", r"nurse"),
    ("emergency room", r"(?-i:\b(ED|ER)\b)|emergency", r"(?-i:\b(ED|ER)\b)|emergency|911"),
    ("primary care", r"\bPCP\b|primary care", r"\bPCP\b|primary care|regular doctor|family doctor|main doctor"),
    ("follow-up appointment", r"follow[- ]?up|appointment", r"follow[- ]?up|appointment|visit|see (your|the|dr)"),
)


DIGIT_WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")
DURATION = re.compile(r"(?<![\d.])([1-9])\s+(?:more\s+)?(days?|weeks?|months?|hours?|times|units?|pounds?|liters?|grams?)\b",
                      re.IGNORECASE)


def instructionText(text: str | None) -> str:
    """The doctor's instructions without the letter greeting and sign-off."""
    lines = (text or "").replace("___", " ").splitlines()
    return "\n".join(l for l in lines if not BOILERPLATE.match(l))


def instructionItems(record: dict) -> list[tuple[str, str]]:
    """What the doctor told the patient to do or know: (label, pattern to look for in our document)."""
    ref = instructionText(record.get("refInstructions"))
    if not ref.strip():
        return []
    items = [(label, docPattern) for label, refPattern, docPattern in ACTION_ITEMS
             if re.search(refPattern, ref, re.IGNORECASE)]
    for n in sorted(numberTokens(ref)):
        if not re.fullmatch(r"[0-9]", n):
            items.append((n, rf"(?<![\d.]){re.escape(n)}(?![\d]|\.\d)"))
    # small numbers only count when they are a duration or amount: "8 weeks", "2 units"
    for n, unit in sorted(set(DURATION.findall(ref))):
        word = DIGIT_WORDS[int(n)]
        stem = unit.lower().rstrip("s")
        items.append((f"{n} {stem}", rf"\b({n}|{word})(\s|-)+(more\s+)?{stem}"))
    lowered = ref.lower()
    for drug in parseMedications(record.get("dischargeMedsSection")):
        if drug[:5] in lowered:
            items.append((drug, re.escape(drug[:5])))
    for name in sorted(properNouns(ref)):
        items.append((name, re.escape(name[:5])))
    seen: set[str] = set()
    return [i for i in items if not (i[0] in seen or seen.add(i[0]))]


def instructionCoverage(record: dict, document: str) -> tuple[int, list[str]]:
    """How many of the doctor's items the document carries, and which it misses."""
    items = instructionItems(record)
    # headings like "Your follow-up" would count as covering a follow-up item on their own
    body = "\n".join(l for l in (document or "").splitlines()
                     if not isHeaderLine(l) and not l.strip().startswith("YOUR "))
    missed = [label for label, pattern in items if not re.search(pattern, body, re.IGNORECASE)]
    return len(items), missed


@dataclass
class Score:
    medTotal: int
    medFound: int
    medRecall: float
    highRiskTotal: int
    highRiskMissing: int
    allergyTotal: int
    allergyFound: int
    allergyRecall: float
    readingGrade: float | None
    patientVoice: float
    sections: int
    repetitionRate: float
    degenerate: bool
    medRestatements: int
    narrativeChars: int
    unsupportedNumbers: list[str] = field(default_factory=list)
    speculative: int = 0
    simplifiedSections: int = 0
    simplifyRejected: int = 0
    simplifyReasons: dict[str, int] = field(default_factory=dict)
    missingMeds: list[str] = field(default_factory=list)
    missingHighRisk: list[str] = field(default_factory=list)
    fromInstructions: bool = False
    instructionItems: int = 0
    instructionCoverage: float | None = None
    missedInstructions: list[str] = field(default_factory=list)
    draftCoverage: float | None = None
    conflicts: list[str] = field(default_factory=list)
    strategy: str = "generate"
    filledSections: list[str] = field(default_factory=list)
    explainedTerms: list[str] = field(default_factory=list)


def sourceText(record: dict, withInstructions: bool = False) -> str:
    keys = ("modelInput", "dischargeMedsSection", "allergiesSection", "dispositionSection")
    return " ".join(str(record.get(k) or "") for k in keys + (("refInstructions",) if withInstructions else ()))


def score(record: dict, document: str, narrative: str, raw: str | None = None,
          withInstructions: bool = False) -> Score:
    """Facts scored on the full document; voice, grade and restatement on model text only.

    Repetition is measured on the raw output, so a loop still counts after dedupe.
    """
    flat = normalize(document)
    meds = parseMedications(record.get("dischargeMedsSection"))
    allergies = parseAllergies(record.get("allergiesSection"))
    missing = [m for m in meds if not present(m, flat)]
    highRisk = [m for m in meds if isHighRisk(m)]
    missingHighRisk = [m for m in highRisk if not present(m, flat)]
    found = [a for a in allergies if present(a, flat)]
    rate, _ = repetition(raw if raw is not None else narrative)
    itemCount, missedItems = instructionCoverage(record, document)
    return Score(
        medTotal=len(meds),
        medFound=len(meds) - len(missing),
        medRecall=round((len(meds) - len(missing)) / len(meds), 4) if meds else 1.0,
        highRiskTotal=len(highRisk),
        highRiskMissing=len(missingHighRisk),
        allergyTotal=len(allergies),
        allergyFound=len(found),
        allergyRecall=round(len(found) / len(allergies), 4) if allergies else 1.0,
        readingGrade=readingGrade(narrative),
        patientVoice=round(patientVoice(narrative), 3),
        sections=sectionsPresent(narrative),
        repetitionRate=round(rate, 3),
        degenerate=isDegenerate(raw if raw is not None else narrative),
        medRestatements=medRestatements(narrative, meds),
        narrativeChars=len(narrative or ""),
        unsupportedNumbers=unsupportedNumbers(narrative, sourceText(record, withInstructions))
        + inventedDays(narrative, sourceText(record, withInstructions)),
        conflicts=durationConflicts(narrative, record, withInstructions),
        speculative=speculativeSentences(narrative,
                                         (record.get("refInstructions") or "") if withInstructions else ""),
        missingMeds=missing,
        missingHighRisk=missingHighRisk,
        fromInstructions=withInstructions,
        instructionItems=itemCount,
        instructionCoverage=round(1 - len(missedItems) / itemCount, 4) if itemCount else None,
        missedInstructions=missedItems,
    )
