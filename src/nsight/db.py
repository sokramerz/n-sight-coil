"""Local DuckDB store for the cohort and every generated document.

The file lives under data/interim, which git ignores. Only one process can hold
it for writing, so stop the API before running the CLI loaders.
"""
from __future__ import annotations

import json
import threading
from dataclasses import asdict
from pathlib import Path

import duckdb

from nsight.generate.pipeline import GenerationResult
from nsight.ingest.medications import isHighRisk, parseAllergies, parseMedications
from nsight.ingest.segmentation import leaks

SCHEMA = """
CREATE TABLE IF NOT EXISTS admissions (
    hadm_id BIGINT PRIMARY KEY,
    subject_id BIGINT,
    note_id VARCHAR,
    service VARCHAR,
    admit_time VARCHAR,
    disch_time VARCHAR,
    los_days INTEGER,
    model_input VARCHAR,
    ref_instructions VARCHAR,
    meds_section VARCHAR,
    allergies_section VARCHAR,
    disposition_section VARCHAR,
    diagnoses VARCHAR,
    med_count INTEGER,
    high_risk_count INTEGER,
    allergy_count INTEGER,
    leaks BOOLEAN
);
CREATE SEQUENCE IF NOT EXISTS document_ids START 1;
CREATE TABLE IF NOT EXISTS documents (
    id BIGINT PRIMARY KEY DEFAULT nextval('document_ids'),
    hadm_id BIGINT,
    mode VARCHAR,
    model VARCHAR,
    include_med_list BOOLEAN,
    source VARCHAR,
    created_at TIMESTAMP DEFAULT current_timestamp,
    raw VARCHAR,
    narrative VARCHAR,
    document VARCHAR,
    sections VARCHAR,
    score VARCHAR,
    warnings VARCHAR,
    removed INTEGER,
    prompt_tokens INTEGER,
    duration_ms INTEGER
);
CREATE TABLE IF NOT EXISTS extra_scores (
    document_id BIGINT,
    metric VARCHAR,
    value DOUBLE,
    computed_at TIMESTAMP DEFAULT current_timestamp
);
"""

ADMISSION_COLUMNS = (
    "hadm_id, subject_id, note_id, service, admit_time, disch_time, los_days, model_input, "
    "ref_instructions, meds_section, allergies_section, disposition_section, diagnoses, "
    "med_count, high_risk_count, allergy_count, leaks"
)


class StoreLocked(RuntimeError):
    pass


def toInt(value) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def toList(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return [value]
    return [str(v) for v in value if v]


def rowToRecord(row: dict) -> dict:
    """Shape a stored admission like a cohort row, which is what the pipeline expects."""
    return {
        "hadm_id": row["hadm_id"],
        "modelInput": row["model_input"],
        "refInstructions": row["ref_instructions"],
        "dischargeMedsSection": row["meds_section"],
        "allergiesSection": row["allergies_section"],
        "dispositionSection": row["disposition_section"],
        "dischargeDiagnoses": toList(row["diagnoses"]),
    }


class Store:
    def __init__(self, path: Path, readOnly: bool = False):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.con = duckdb.connect(str(path), read_only=readOnly)
        except duckdb.IOException as exc:
            raise StoreLocked(
                f"{path.name} is in use by another process. Stop the API, then run this again."
            ) from exc
        self.lock = threading.Lock()
        if not readOnly:
            self.con.execute(SCHEMA)

    def close(self) -> None:
        self.con.close()

    def query(self, sql: str, params: list | None = None) -> list[dict]:
        with self.lock:
            cur = self.con.execute(sql, params or [])
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    # ------------------------------------------------------------------ cohort

    def loadCohort(self, rows: list[dict]) -> dict:
        loaded = leaked = 0
        with self.lock:
            for row in rows:
                hadm = toInt(row.get("hadm_id"))
                if hadm is None:
                    continue
                meds = parseMedications(row.get("dischargeMedsSection"))
                isLeak = leaks(row.get("modelInput"), row.get("refInstructions"))
                leaked += isLeak
                self.con.execute(
                    f"INSERT OR REPLACE INTO admissions ({ADMISSION_COLUMNS}) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [hadm, toInt(row.get("subject_id")), row.get("note_id"),
                     row.get("curr_service"), str(row.get("admittime") or ""),
                     str(row.get("dischtime") or ""), toInt(row.get("lengthOfStayDays")),
                     row.get("modelInput"), row.get("refInstructions"),
                     row.get("dischargeMedsSection"), row.get("allergiesSection"),
                     row.get("dispositionSection"),
                     json.dumps(toList(row.get("dischargeDiagnoses"))),
                     len(meds), sum(1 for m in meds if isHighRisk(m)),
                     len(parseAllergies(row.get("allergiesSection"))), isLeak],
                )
                loaded += 1
        return {"loaded": loaded, "leaked": leaked}

    def countAdmissions(self) -> int:
        return self.query("SELECT count(*) AS n FROM admissions")[0]["n"]

    def listAdmissions(self, search: str = "", limit: int = 50, offset: int = 0,
                       includeLeaks: bool = False) -> tuple[list[dict], int]:
        where, params = [], []
        if not includeLeaks:
            where.append("NOT a.leaks")
        if search:
            term = f"%{search.lower()}%"
            where.append("(CAST(a.hadm_id AS VARCHAR) LIKE ? OR lower(a.diagnoses) LIKE ? "
                         "OR lower(a.meds_section) LIKE ?)")
            params += [term, term, term]
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        total = self.query(f"SELECT count(*) AS n FROM admissions a {clause}", params)[0]["n"]
        rows = self.query(
            f"""SELECT a.hadm_id, a.subject_id, a.service, a.admit_time, a.disch_time,
                       a.los_days, a.diagnoses, a.med_count, a.high_risk_count,
                       a.allergy_count, a.leaks,
                       (SELECT count(*) FROM documents d WHERE d.hadm_id = a.hadm_id) AS doc_count
                FROM admissions a {clause}
                ORDER BY a.hadm_id LIMIT ? OFFSET ?""",
            params + [limit, offset],
        )
        return rows, total

    def getAdmission(self, hadmId: int) -> dict | None:
        rows = self.query(
            f"SELECT {ADMISSION_COLUMNS}, "
            "(SELECT count(*) FROM documents d WHERE d.hadm_id = a.hadm_id) AS doc_count "
            "FROM admissions a WHERE hadm_id = ?", [hadmId])
        return rows[0] if rows else None

    # --------------------------------------------------------------- documents

    def addDocument(self, hadmId: int, result: GenerationResult, source: str) -> int:
        with self.lock:
            return self.con.execute(
                """INSERT INTO documents (hadm_id, mode, model, include_med_list, source, raw,
                       narrative, document, sections, score, warnings, removed,
                       prompt_tokens, duration_ms)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
                [hadmId, result.mode, result.model, result.includeMedList, source,
                 result.raw, result.narrative, result.document, json.dumps(result.sections),
                 json.dumps(asdict(result.score)), json.dumps(result.warnings),
                 result.dosingSentencesRemoved, result.promptTokens, result.durationMs],
            ).fetchone()[0]

    def listDocuments(self, hadmId: int) -> list[dict]:
        return self.query("SELECT * FROM documents WHERE hadm_id = ? ORDER BY id DESC", [hadmId])

    def getDocument(self, docId: int) -> dict | None:
        rows = self.query("SELECT * FROM documents WHERE id = ?", [docId])
        return rows[0] if rows else None

    def deleteDocuments(self, source: str) -> int:
        with self.lock:
            n = self.con.execute("SELECT count(*) FROM documents WHERE source = ?", [source]).fetchone()[0]
            self.con.execute("DELETE FROM documents WHERE source = ?", [source])
            return n

    def addExtraScores(self, documentId: int, values: dict[str, float | None]) -> None:
        """Scores computed after generation. Rescoring adds rows; reads take the newest."""
        with self.lock:
            for metric, value in values.items():
                self.con.execute("INSERT INTO extra_scores (document_id, metric, value) VALUES (?,?,?)",
                                 [documentId, metric, value])

    def extraScores(self, documentIds: list[int]) -> dict[int, dict[str, float | None]]:
        if not documentIds:
            return {}
        marks = ",".join("?" * len(documentIds))
        rows = self.query(f"""SELECT document_id, metric, value FROM (
            SELECT *, row_number() OVER (PARTITION BY document_id, metric ORDER BY computed_at DESC) AS rn
            FROM extra_scores WHERE document_id IN ({marks})) WHERE rn = 1""", documentIds)
        out: dict[int, dict[str, float | None]] = {}
        for r in rows:
            out.setdefault(r["document_id"], {})[r["metric"]] = r["value"]
        return out

    def documentScores(self) -> list[dict]:
        """Latest document per admission and mode, for the evaluation summary."""
        return self.query(
            """SELECT mode, model, score, removed FROM (
                   SELECT *, row_number() OVER (PARTITION BY hadm_id, mode, model ORDER BY id DESC) AS rn
                   FROM documents) WHERE rn = 1""")
