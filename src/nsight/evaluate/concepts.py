"""Medical concept recall and precision, in the spirit of MEDCON (Discharge Me!, BioNLP 2024).

A biomedical NER model pulls medications, conditions, symptoms, tests and procedures
out of the text. Recall is the share of concepts in the doctor's instructions that
the summary still mentions. Precision is the share of concepts in the summary that
appear somewhere in the record the pipeline was given.

Unlike the coverage check, nothing here is a list we wrote ourselves, so the rewrite
step can't be tuned to it. Runs locally; the model downloads once from Hugging Face.
"""
from __future__ import annotations

import json
import os
import re
from typing import Protocol

from nsight.generate.glossary import TERMS

DEFAULT_MODEL = "d4data/biomedical-ner-all"
KEEP_LABELS = {"Medication", "Disease_disorder", "Sign_symptom", "Diagnostic_procedure", "Therapeutic_procedure"}
STOPWORDS = {"a", "an", "the", "your", "you", "of", "and", "or", "to", "in", "on", "for", "with", "any", "some",
             "this", "that", "these", "my", "his", "her", "their", "new", "more", "less"}
CHUNK_CHARS = 1200


class Extractor(Protocol):
    def extract(self, text: str) -> set[str]: ...


def normalize(span: str) -> str:
    tokens = re.findall(r"[a-z0-9]+", span.lower())
    tokens = [t[:-1] if len(t) > 3 and t.endswith("s") else t for t in tokens if t not in STOPWORDS]
    return " ".join(tokens)


def chunks(text: str) -> list[str]:
    """Pieces short enough for a 512-token model, split on line or sentence ends."""
    out, current = [], ""
    for piece in re.split(r"(?<=[.!?\n])\s+", text or ""):
        if len(current) + len(piece) > CHUNK_CHARS and current:
            out.append(current)
            current = ""
        current = f"{current} {piece}".strip()
    if current:
        out.append(current)
    return out


class NerExtractor:
    def __init__(self, model: str | None = None) -> None:
        from transformers import pipeline  # heavy, only loaded when scoring concepts
        import torch

        self.pipe = pipeline("token-classification", model=model or os.environ.get("NSIGHT_NER_MODEL", DEFAULT_MODEL),
                             aggregation_strategy="simple", device=0 if torch.cuda.is_available() else -1)

    def extract(self, text: str) -> set[str]:
        pieces = chunks(text)
        if not pieces:
            return set()
        found = set()
        for entities in self.pipe(pieces, batch_size=16):
            for entity in entities:
                if entity.get("entity_group") in KEEP_LABELS:
                    concept = normalize(entity["word"])
                    if len(concept) >= 3:
                        found.add(concept)
        return found


def mentions(concept: str, text: str) -> bool:
    """Every word of the concept appears in the text (order and inflection aside)."""
    words = set(normalize(text).split())
    return all(token in words for token in concept.split())


GLOSSARY_ASIDES = [f" ({explanation})" for _, _, explanation in TERMS]


def withoutGlossary(text: str) -> str:
    for aside in GLOSSARY_ASIDES:
        text = text.replace(aside, "")
    return text


def conceptScores(extractor: Extractor, doctorText: str, sourceText: str, summaryText: str,
                  writtenText: str) -> dict[str, float | None]:
    """recall against the doctor's instructions, precision against the whole record.

    writtenText is the summary minus sections filled from fixed text, so a warning
    sign list we chose to add isn't counted as unsupported.
    """
    doctor = extractor.extract(doctorText) if doctorText else set()
    written = extractor.extract(withoutGlossary(writtenText)) if writtenText else set()
    return {
        "conceptRecall": round(sum(mentions(c, summaryText) for c in doctor) / len(doctor), 4) if doctor else None,
        "conceptPrecision": round(sum(mentions(c, sourceText) for c in written) / len(written), 4) if written else None,
        "doctorConcepts": float(len(doctor)),
        "summaryConcepts": float(len(written)),
    }


def scoreRun(store, tag: str, extractor: Extractor, force: bool = False, progress=None) -> int:
    """Concept scores for the latest document per admission in a run. Returns how many were scored."""
    from nsight.ingest.cleaning import stripPlaceholders

    rows = store.query("""SELECT id, hadm_id, narrative, sections, score FROM (
        SELECT *, row_number() OVER (PARTITION BY hadm_id ORDER BY id DESC) AS rn
        FROM documents WHERE source = ?) WHERE rn = 1 ORDER BY hadm_id""", [tag])
    done = store.extraScores([r["id"] for r in rows])
    scored = 0
    for i, row in enumerate(rows, 1):
        if not force and "conceptRecall" in done.get(row["id"], {}):
            continue
        admission = store.getAdmission(row["hadm_id"])
        filled = set(json.loads(row["score"] or "{}").get("filledSections") or [])
        written = "\n\n".join(s["text"] for s in json.loads(row["sections"] or "[]") if s.get("header") not in filled)
        source = "\n\n".join(str(admission.get(k) or "") for k in
                             ("model_input", "ref_instructions", "meds_section", "diagnoses"))
        scores = conceptScores(extractor, stripPlaceholders(admission.get("ref_instructions")) or "",
                               source, row["narrative"] or "", written)
        store.addExtraScores(row["id"], scores)
        scored += 1
        if progress:
            progress(i, len(rows), row["hadm_id"], scores)
    return scored
