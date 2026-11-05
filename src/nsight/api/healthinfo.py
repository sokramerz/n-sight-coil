"""Drug and health-topic reference data for the patient Health tab.

The files in nsight/FAQ/faq_data were exported from the Neo4j graphs (DrugBank drug
interactions, side effects, and MedlinePlus health topics). They're loaded once,
on first use, and only what one patient needs is sent to the browser:
interactions.json alone is too big to ship whole.
"""
from __future__ import annotations

import json
import os
import re
from functools import cached_property
from pathlib import Path

from nsight.generate.sideeffects import rankSideEffects
from nsight.ingest.drugnames import candidates, norm, plainCase

DEFAULT_DIR = Path(__file__).resolve().parents[1] / "FAQ" / "faq_data"

# discharge diagnoses are often abbreviated; MedlinePlus titles never are
ABBREVIATIONS = {
    "GI": "gastrointestinal", "UTI": "urinary tract infection", "CHF": "congestive heart failure",
    "DVT": "deep vein thrombosis", "MI": "heart attack", "STEMI": "heart attack", "NSTEMI": "heart attack",
    "CKD": "chronic kidney disease", "ESRD": "kidney failure", "AKI": "kidney failure", "ARF": "kidney failure",
    "A-?[Ff]ib": "atrial fibrillation", "HTN": "hypertension", "CAD": "coronary artery disease",
    "PNA": "pneumonia", "CVA": "stroke", "TIA": "transient ischemic attack", "OSA": "sleep apnea",
    "T2DM": "type 2 diabetes", "T1DM": "diabetes type 1", "DM2": "type 2 diabetes", "DM1": "diabetes type 1",
    "HLD": "hypercholesterolemia", "EtOH": "alcoholism",
}
ABBREVIATION = re.compile(r"\b(" + "|".join(ABBREVIATIONS) + r")\b")
SYNONYMS = [
    (re.compile(r"\bbleed\b", re.IGNORECASE), "bleeding"),
    (re.compile(r"\btype (?:1|i) diabetes(?: mellitus)?\b", re.IGNORECASE), "diabetes type 1"),
    (re.compile(r"\bacute kidney injury\b", re.IGNORECASE), "kidney failure"),
    (re.compile(r"\b(kidney|renal|liver|heart|lung) transplant\b", re.IGNORECASE), r"\1 transplantation"),
]


def expandDiagnosis(text: str) -> str:
    def full(match: re.Match) -> str:
        word = match.group(1)
        return next(v for k, v in ABBREVIATIONS.items() if re.fullmatch(k, word))
    text = ABBREVIATION.sub(full, text)
    for pattern, replacement in SYNONYMS:
        text = pattern.sub(replacement, text)
    return text


# everyday words that have a MedlinePlus page but don't need a pop-up
EVERYDAY = {"pain", "fever", "fevers", "swelling", "headache", "headaches", "fatigue", "falls", "fall", "cough",
            "nausea", "vomiting", "constipation", "dizziness", "bleeding", "infection", "infections", "rest", "sleep"}

QUESTION = re.compile(r"(?:(?<=[.!?:] )|^)((?:What|How|Who|Why|When|Where|Can|Is|Are|Do|Does|Should|Will)\b"
                      r"[^.!?]{3,140}\?)")


def tidy(text: str) -> str:
    """The graph export leaves a space before punctuation where HTML tags were removed."""
    return re.sub(r"\s+([,.;:)])", r"\1", re.sub(r"\(\s+", "(", text)).strip()


def questionParts(title: str, summary: str) -> list[dict]:
    """MedlinePlus summaries are mostly written as questions and answers; split them on the questions."""
    summary = tidy(summary)
    questions = list(QUESTION.finditer(summary))
    if not questions:
        return [{"question": f"What is {title.lower()}?" if len(title.split()) <= 4 else title, "answer": summary}]
    parts = []
    if questions[0].start() > 0:
        parts.append({"question": f"About {title.lower()}", "answer": summary[:questions[0].start()].strip()})
    for i, q in enumerate(questions):
        end = questions[i + 1].start() if i + 1 < len(questions) else len(summary)
        answer = summary[q.end():end].strip()
        if answer:
            parts.append({"question": q.group(1), "answer": answer})
    return parts


class HealthInfo:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = Path(directory or os.environ.get("NSIGHT_FAQ_DIR") or DEFAULT_DIR)

    def load(self, name: str):
        path = self.directory / name
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    @cached_property
    def drugs(self) -> dict[str, dict]:
        """Lowercase DrugBank name -> {id, name, interactions (lowercase names), sideEffects}."""
        out: dict[str, dict] = {}
        for row in self.load("interactions.json") or []:
            out[norm(row["name"])] = {"id": row["id"], "name": row["name"], "sideEffects": [],
                                      "interactions": {norm(n) for n in row.get("interacting_drugs") or []}}
        for row in self.load("side_effects.json") or []:
            entry = out.setdefault(norm(row["name"]), {"id": row["id"], "name": row["name"], "interactions": set(),
                                                       "sideEffects": []})
            entry["sideEffects"] = row.get("side_effects") or []
        return out

    @cached_property
    def topicIndex(self) -> tuple[list[tuple[str, str]], dict[str, dict]]:
        data = self.load("summaries.json") or {"terms": {}, "topics": {}}
        # longest first, so "congestive heart failure" wins over "heart failure"
        index = {norm(t): tid for t, tid in data["terms"].items()}
        # "urinary tract infections" is the only title, but diagnoses say "urinary tract infection"
        for term, tid in list(index.items()):
            if term.endswith("s") and not term.endswith(("ss", "is", "us")) and len(term) > 5:
                index.setdefault(term[:-1], tid)
        terms = sorted(index.items(), key=lambda x: -len(x[0]))
        return terms, data["topics"]

    def warm(self) -> None:
        self.drugs
        self.topicIndex

    @property
    def available(self) -> bool:
        return bool(self.drugs) or bool(self.topicIndex[1])

    def matchDrug(self, medName: str) -> list[dict]:
        for names in candidates(medName):
            found = [self.drugs[n] for n in names if n in self.drugs]
            if found and len(found) == len(names):
                return found
        return []

    def medicines(self, medNames: list[str]) -> list[dict]:
        """For each medication line: its DrugBank match and its side effects, serious ones first."""
        out = []
        for name in medNames:
            drugs = self.matchDrug(name)
            effects = sorted({e for d in drugs for e in d["sideEffects"]}, key=str.lower)
            out.append({"listedAs": plainCase(name),
                        "matches": [{"drugbankId": d["id"], "name": d["name"]} for d in drugs],
                        "sideEffects": rankSideEffects(effects)})
        return out

    def interactions(self, medNames: list[str]) -> list[dict]:
        """Pairs of the patient's medicines that DrugBank lists an interaction for, in either direction."""
        matched = [(name, self.matchDrug(name)) for name in medNames]
        pairs = []
        for i, (first, firstDrugs) in enumerate(matched):
            for second, secondDrugs in matched[i + 1:]:
                listed = [(a["name"], b["name"]) for a in firstDrugs for b in secondDrugs
                          if norm(b["name"]) in a["interactions"] or norm(a["name"]) in b["interactions"]]
                if listed:
                    pairs.append({"first": plainCase(first), "second": plainCase(second),
                                  "drugs": [f"{a} + {b}" for a, b in listed]})
        return pairs

    def topics(self, diagnoses: list[str], limit: int = 6) -> list[dict]:
        """MedlinePlus topics whose title or alias appears in the diagnoses, in diagnosis order."""
        terms, topics = self.topicIndex
        out, seen = [], set()
        for diagnosis in diagnoses:
            text = f" {norm(expandDiagnosis(diagnosis))} "
            for term, tid in terms:
                if tid in seen or f" {term} " not in text:
                    continue
                seen.add(tid)
                topic = topics.get(tid)
                if topic:
                    title = " ".join(topic["title"].split())
                    out.append({"id": tid, "title": title, "summary": tidy(topic["summary"]),
                                "parts": questionParts(title, topic["summary"]), "matchedOn": diagnosis})
                break  # one topic per diagnosis: the longest matching term
            if len(out) >= limit:
                break
        return out

    def termLinks(self, sections: list[list[str]], diagnoses: list[str]) -> list[dict]:
        """Where the patient's own conditions first appear in their instructions, for pop-ups.

        `sections` is the instruction text as section -> items. One link per condition, at its
        first appearance in reading order. Positions are character offsets within the item.
        """
        terms, topics = self.topicIndex
        links = []
        for topic in self.topics(diagnoses, limit=10):
            words = {t for t, tid in terms if tid == topic["id"] and t not in EVERYDAY}
            abbreviations = [a for a, full in ABBREVIATIONS.items() if norm(full) in words]
            patterns = [re.compile(rf"(?<![\w-]){re.escape(w)}(?![\w-])", re.IGNORECASE)
                        for w in sorted(words, key=len, reverse=True)]
            patterns += [re.compile(rf"\b(?:{a})\b") for a in abbreviations]
            found = None
            for si, items in enumerate(sections):
                for ii, item in enumerate(items):
                    hits = [m for p in patterns if (m := p.search(item))]
                    if hits:
                        first = min(hits, key=lambda m: (m.start(), -len(m.group(0))))
                        found = {"section": si, "item": ii, "start": first.start(), "end": first.end(),
                                 "text": first.group(0), "topicId": topic["id"], "title": topic["title"]}
                        break
                if found:
                    break
            if found:
                links.append(found)
        return links
