"""Compare tagged runs on the admissions they all share. Used by the CLI and the API."""
from __future__ import annotations

import json
import math
import random
import statistics
from dataclasses import dataclass, field

from nsight.db import Store, rowToRecord
from nsight.evaluate.metrics import instructionCoverage, readability, readingGrade

BOOTSTRAP_DRAWS = 2000


def bootstrapCi(values: list[float], draws: int = BOOTSTRAP_DRAWS) -> tuple[float, float] | None:
    """95% percentile bootstrap interval for the mean. Seeded so a rerun gives the same interval."""
    if len(values) < 2:
        return None
    rng = random.Random(0)
    means = sorted(statistics.fmean(rng.choices(values, k=len(values))) for _ in range(draws))
    return means[int(0.025 * draws)], means[int(0.975 * draws) - 1]


def wilcoxon(differences: list[float]) -> float | None:
    """Two-sided Wilcoxon signed-rank p for paired differences, or None when it can't run."""
    nonzero = [d for d in differences if d != 0]
    if len(nonzero) < 2:
        return None
    try:
        from scipy.stats import wilcoxon as test
    except ImportError:
        return None
    return float(test(nonzero).pvalue)


def signTest(wins: int, losses: int) -> float:
    n = wins + losses
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(min(wins, losses) + 1)) / 2 ** n)


METRICS = (
    # label, how to read it from (score, removed), whether higher is better
    ("reading grade", lambda s, r: s["readingGrade"], False),
    ("patient voice", lambda s, r: s["patientVoice"], True),
    ("all 4 sections", lambda s, r: float(s["sections"] == 4), True),
    ("unsupported numbers", lambda s, r: float(len(s.get("unsupportedNumbers") or [])), False),
    ("speculative sentences", lambda s, r: float(s.get("speculative") or 0), False),
    ("course conflicts", lambda s, r: float(len(s.get("conflicts") or [])), False),
    ("restated dosing", lambda s, r: float(bool(s["medRestatements"] or r)), False),
    ("repetition loop", lambda s, r: float(s["degenerate"]), False),
    ("doctor's items covered", lambda s, r: s.get("instructionCoverage"), True),
    ("concept recall", lambda s, r: s.get("conceptRecall"), True),
    ("concept precision", lambda s, r: s.get("conceptPrecision"), True),
    ("SMOG grade", lambda s, r: s.get("smog"), False),
    ("Dale-Chall score", lambda s, r: s.get("daleChall"), False),
    ("difficult words", lambda s, r: s.get("difficultWords"), False),
    ("unexplained abbreviations", lambda s, r: s.get("jargon"), False),
    ("filled from the record", lambda s, r: float(bool(s.get("filledSections"))), None),
    ("terms explained", lambda s, r: float(len(s.get("explainedTerms") or [])), None),
    ("narrative length", lambda s, r: float(s["narrativeChars"]), None),
)


def loadTag(store: Store, tag: str) -> dict[int, tuple[dict, int]]:
    """Latest document per admission, its score plus readability and any concept scores."""
    rows = store.query("""SELECT id, hadm_id, score, removed, document, narrative FROM (
        SELECT *, row_number() OVER (PARTITION BY hadm_id ORDER BY id DESC) AS rn
        FROM documents WHERE source = ?) WHERE rn = 1""", [tag])
    out = {}
    for r in rows:
        score = json.loads(r["score"])
        if "instructionCoverage" not in score:
            # runs made before the coverage metric existed: score them the same way now
            record = rowToRecord(store.getAdmission(r["hadm_id"]))
            items, missed = instructionCoverage(record, r["document"])
            score["instructionCoverage"] = round(1 - len(missed) / items, 4) if items else None
        score.update(readability(r["narrative"]))
        score["documentId"] = r["id"]
        out[r["hadm_id"]] = (score, r["removed"] or 0)
    extras = store.extraScores([score["documentId"] for score, _ in out.values()])
    for score, _ in out.values():
        score.update(extras.get(score["documentId"], {}))
    return out


@dataclass
class Paired:
    run: str
    label: str
    better: int
    worse: int
    tied: int
    p: float  # exact sign test
    wilcoxonP: float | None = None
    difference: float | None = None  # mean of run minus baseline
    differenceCi: tuple[float, float] | None = None


@dataclass
class Comparison:
    tags: list[str]
    shared: list[int]
    runs: dict[str, dict[int, tuple[dict, int]]]
    means: dict[str, dict[str, float | None]] = field(default_factory=dict)
    cis: dict[str, dict[str, tuple[float, float] | None]] = field(default_factory=dict)
    clinicianGrade: float | None = None
    paired: list[Paired] = field(default_factory=list)


class MissingRun(ValueError):
    pass


def compareRuns(store: Store, tags: list[str]) -> Comparison:
    runs = {tag: loadTag(store, tag) for tag in tags}
    missing = [tag for tag, docs in runs.items() if not docs]
    if missing:
        known = ", ".join(r["source"] for r in store.query("SELECT DISTINCT source FROM documents"))
        raise MissingRun(f"no documents tagged '{missing[0]}'. tags in the database: {known}")
    shared = sorted(set.intersection(*(set(d) for d in runs.values())))
    result = Comparison(tags=tags, shared=shared, runs=runs)

    for label, get, _ in METRICS:
        result.means[label], result.cis[label] = {}, {}
        for tag in tags:
            values = [v for v in (get(*runs[tag][h]) for h in shared) if v is not None]
            result.means[label][tag] = statistics.mean(values) if values else None
            result.cis[label][tag] = bootstrapCi(values)
    grades = [g for g in (readingGrade(store.getAdmission(h)["ref_instructions"]) for h in shared) if g is not None]
    result.clinicianGrade = statistics.mean(grades) if grades else None

    base = tags[0]
    for other in tags[1:]:
        for label, get, higherBetter in METRICS:
            if higherBetter is None:
                continue
            better = worse = tied = 0
            differences = []
            for h in shared:
                a, b = get(*runs[base][h]), get(*runs[other][h])
                if a is not None and b is not None:
                    differences.append(b - a)
                if a is None or b is None or a == b:
                    tied += 1
                elif (b > a) == higherBetter:
                    better += 1
                else:
                    worse += 1
            result.paired.append(Paired(
                run=other, label=label, better=better, worse=worse, tied=tied, p=signTest(better, worse),
                wilcoxonP=wilcoxon(differences),
                difference=statistics.mean(differences) if differences else None,
                differenceCi=bootstrapCi(differences)))
    return result


def listRuns(store: Store) -> list[dict]:
    """Every tagged run with its size, model and when it last wrote, newest first."""
    return store.query("""SELECT source AS tag, count(DISTINCT hadm_id) AS admissions,
                                 any_value(model) AS model, max(created_at) AS lastRun
                          FROM documents GROUP BY source ORDER BY lastRun DESC""")
