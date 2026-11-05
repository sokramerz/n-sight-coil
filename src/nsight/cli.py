"""Load data into the local store and pre-generate documents.

    python -m nsight.cli load-cohort D:/MIMIC-IV/cohortV2.json
    python -m nsight.cli import-results D:/MIMIC-IV/pass10_medgemma_all.json --model medgemma
    python -m nsight.cli generate --n 10 --mode sectional
    python -m nsight.cli generate --n 100 --model gemma3:4b --simplify --tag gemma-simple
    python -m nsight.cli compare cli gemma-simple
    python -m nsight.cli stats

Stop the API first; only one process can write to the database at a time.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from nsight.config import loadSettings
from nsight.db import Store, StoreLocked, rowToRecord
from nsight.evaluate.compare import METRICS, MissingRun, compareRuns
from nsight.generate.model_client import ModelUnavailable, OllamaClient
from nsight.generate.pipeline import (MODES, NARRATIVE_MODES, GenerationFailed,
                                      finalize, generateDocument)

MED_BLOCK = "\n\nYOUR MEDICATIONS\n"


def readRows(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    if text.lstrip().startswith("["):
        return json.loads(text)
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def loadCohort(store: Store, args) -> None:
    result = store.loadCohort(readRows(Path(args.path)))
    print(f"loaded {result['loaded']} admissions, {result['leaked']} flagged by the leak check "
          f"(hidden from the app by default)")


def loadSynthetic(store: Store, args) -> None:
    from nsight.synthetic import syntheticRows
    result = store.loadCohort(syntheticRows())
    print(f"loaded {result['loaded']} fictional admissions (no MIMIC data; outputs are safe to share)")


def importResults(store: Store, args) -> None:
    path = Path(args.path)
    source = f"import:{path.name}"
    if args.replace:
        print(f"removed {store.deleteDocuments(source)} documents from an earlier import")
    imported = skipped = 0
    for entry in readRows(path):
        hadmId = int(entry["hadmId"])
        admission = store.getAdmission(hadmId)
        if admission is None or entry.get("mode") not in MODES:
            skipped += 1
            continue
        mode = entry["mode"]
        raw = entry.get("raw")
        if raw is None:
            raw = entry.get("generated", "")
            if mode in NARRATIVE_MODES:
                raw = raw.split(MED_BLOCK, 1)[0]
        # earlier runs gave narrative modes the full record, medication list included
        result = finalize(rowToRecord(admission), mode, args.model, raw, includeMedList=True)
        store.addDocument(hadmId, result, source)
        imported += 1
    print(f"imported {imported} documents from {path.name}"
          + (f", skipped {skipped} (admission not loaded or unknown mode)" if skipped else ""))


def generate(store: Store, args) -> None:
    settings = loadSettings()
    client = OllamaClient(settings)
    try:
        model = client.resolveModel(args.model or settings.model)
    except ModelUnavailable as exc:
        sys.exit(str(exc))
    rows, _ = store.listAdmissions(limit=args.n, offset=args.offset)
    if args.replace:
        print(f"removed {store.deleteDocuments(args.tag)} documents tagged {args.tag}")
    extra = (" + simplify" if args.simplify else "") + (" + med list" if args.include_med_list else "") + \
        (" from the chart only" if args.chart_only else " from the doctor's instructions")
    print(f"generating {len(rows)} {args.mode}{extra} documents with {model}, tag '{args.tag}'")
    reasonTotals: dict[str, int] = {}
    for i, row in enumerate(rows, 1):
        admission = store.getAdmission(row["hadm_id"])
        print(f"  [{i}/{len(rows)}] {row['hadm_id']} ... ", end="", flush=True)
        try:
            result = generateDocument(rowToRecord(admission), client, mode=args.mode, model=model,
                                      includeMedList=args.include_med_list or None,
                                      simplify=args.simplify, simplifyModel=args.simplify_model,
                                      useInstructions=not args.chart_only, generative=args.generative)
        except (ModelUnavailable, GenerationFailed) as exc:
            print(f"failed: {exc}")
            continue
        store.addDocument(row["hadm_id"], result, source=args.tag)
        s = result.score
        flags = "".join([f"  [{s.strategy}]",
                         f"  numbers {','.join(s.unsupportedNumbers)}" if s.unsupportedNumbers else "",
                         f"  CONFLICT {','.join(s.conflicts)}" if s.conflicts else "",
                         f"  speculative {s.speculative}" if s.speculative else "",
                         f"  simplified {s.simplifiedSections}/{s.simplifiedSections + s.simplifyRejected}"
                         if args.simplify else "",
                         f"  covers {s.instructionItems - len(s.missedInstructions)}/{s.instructionItems}"
                         + (f" (draft {s.draftCoverage:.2f})" if s.draftCoverage is not None else "")
                         if s.instructionItems else ""])
        print(f"{result.durationMs / 1000:.0f}s  sections {s.sections}/4  voice {s.patientVoice:.2f}"
              f"  grade {s.readingGrade}  removed {result.dosingSentencesRemoved}{flags}")
        for reason, count in s.simplifyReasons.items():
            reasonTotals[reason] = reasonTotals.get(reason, 0) + count
    if reasonTotals:
        print("\nfailed rewrite checks, all attempts (one attempt can fail several):")
        for reason, count in sorted(reasonTotals.items(), key=lambda x: -x[1]):
            print(f"  {reason:<20}{count:>4}")


def compare(store: Store, args) -> None:
    try:
        result = compareRuns(store, args.tags)
    except MissingRun as exc:
        sys.exit(str(exc))
    shared, runs, means = result.shared, result.runs, result.means
    clinicianGrade, paired, base = result.clinicianGrade, result.paired, args.tags[0]
    print(f"{len(shared)} admissions in every run\n")

    width = max(max(len(t) for t in args.tags), 22) + 2

    def cell(label: str, tag: str) -> str:
        value, ci = means[label][tag], result.cis[label][tag]
        if value is None:
            return f"{'-':>{width}}"
        return f"{f'{value:.2f} [{ci[0]:.2f}, {ci[1]:.2f}]' if ci else f'{value:.2f}':>{width}}"

    print(f"{'':<26}" + "".join(f"{t:>{width}}" for t in args.tags) + "    (mean [95% CI])")
    for label in means:
        print(f"{label:<26}" + "".join(cell(label, tag) for tag in args.tags))
    if clinicianGrade is not None:
        print(f"\nclinician's own instructions on the same admissions: reading grade {clinicianGrade:.2f}")
    for other in args.tags[1:]:
        print(f"\npaired, {other} vs {base}  (better / worse / tied, sign test p, difference [95% CI], Wilcoxon p)")
        for row in paired:
            if row.run == other:
                diff = (f"{row.difference:+.3f}" + (f" [{row.differenceCi[0]:+.3f}, {row.differenceCi[1]:+.3f}]"
                                                    if row.differenceCi else "")) if row.difference is not None else "-"
                wil = f"{row.wilcoxonP:.3g}" if row.wilcoxonP is not None else "-"
                print(f"  {row.label:<26}{row.better:>5} {row.worse:>5} {row.tied:>5}   p = {row.p:<9.3g}"
                      f"{diff:<28}{wil}")
    print("\nmetrics are automatic proxies; read a sample of documents before trusting a difference")

    if getattr(args, "out", None):
        writeComparison(Path(args.out), args.tags, shared, runs, means, clinicianGrade, paired)


def writeComparison(out: Path, tags: list[str], shared: list[int], runs: dict, means: dict,
                    clinicianGrade: float | None, paired: list) -> None:
    """Summary and per-admission CSVs. Scores and IDs only, no note text."""
    import csv
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([f"{len(shared)} admissions in every run"])
        w.writerow(["metric"] + tags)
        for label, byTag in means.items():
            w.writerow([label] + ["" if v is None else round(v, 3) for v in byTag.values()])
        if clinicianGrade is not None:
            w.writerow(["clinician's own reading grade", round(clinicianGrade, 3)])
        w.writerow([])
        w.writerow(["paired vs " + tags[0], "metric", "better", "worse", "tied", "sign test p",
                    "mean difference", "difference CI low", "difference CI high", "Wilcoxon p"])
        for row in paired:
            ci = row.differenceCi or (None, None)
            w.writerow([row.run, row.label, row.better, row.worse, row.tied, round(row.p, 4),
                        "" if row.difference is None else round(row.difference, 4),
                        "" if ci[0] is None else round(ci[0], 4), "" if ci[1] is None else round(ci[1], 4),
                        "" if row.wilcoxonP is None else round(row.wilcoxonP, 4)])
    perAdmission = out.with_name(out.stem + "-perAdmission.csv")
    with perAdmission.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["hadm_id", "run"] + [label for label, _, _ in METRICS])
        for h in shared:
            for tag in tags:
                row = [get(*runs[tag][h]) for _, get, _ in METRICS]
                w.writerow([h, tag] + ["" if v is None else round(v, 3) for v in row])
    print(f"wrote {out} and {perAdmission}")


def scoreConcepts(store: Store, args) -> None:
    from nsight.evaluate.concepts import NerExtractor, scoreRun
    print("loading the concept model (downloads once)...")
    extractor = NerExtractor(args.model)

    def progress(i, total, hadmId, scores):
        recall, precision = scores["conceptRecall"], scores["conceptPrecision"]
        print(f"  [{i}/{total}] {hadmId}  recall {'-' if recall is None else f'{recall:.2f}'}"
              f"  precision {'-' if precision is None else f'{precision:.2f}'}")

    for tag in args.tags:
        print(f"scoring '{tag}'")
        n = scoreRun(store, tag, extractor, force=args.force, progress=progress)
        print(f"scored {n} documents in '{tag}'" + ("" if n else " (all were already scored; --force to redo)"))


def stats(store: Store, args) -> None:
    rows = store.query("SELECT mode, model, source, count(*) AS n FROM documents "
                       "GROUP BY ALL ORDER BY source, mode")
    print(f"{store.countAdmissions()} admissions loaded")
    for r in rows:
        print(f"  {r['n']:>4}  {r['mode']:<11} {r['model']:<14} {r['source']}")


def export(store: Store, args) -> None:
    from nsight.review import exportRows, writeExport
    try:
        header, rows = exportRows(store, args.tags, args.n)
    except ValueError as exc:
        sys.exit(str(exc))
    out = args.out or store.path.parent / f"sideBySide-{'-'.join(args.tags)}.xlsx"
    written = writeExport(out, header, rows)
    print(f"{len(rows)} admissions written to {written}")
    if not written.endswith(".xlsx") and str(out).endswith(".xlsx"):
        print("openpyxl is not installed, so this is a CSV. pip install openpyxl for the .xlsx")
    if store.path.name != "synthetic.duckdb":
        print("this file contains MIMIC note text: keep it local, never commit or share it")


def review(store: Store, args) -> None:
    from nsight.review import buildReview
    try:
        page, n = buildReview(store, args.tags, args.n)
    except ValueError as exc:
        sys.exit(str(exc))
    out = Path(args.out) if args.out else store.path.parent / f"review-{'-'.join(args.tags)}.html"
    out.write_text(page, encoding="utf-8")
    print(f"{n} admissions written to {out}")
    if store.path.name != "synthetic.duckdb":
        print("this file contains MIMIC note text: keep it local, never commit or share it")
    if not args.no_open:
        import webbrowser
        webbrowser.open(out.resolve().as_uri())


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m nsight.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("load-cohort", help="load the BigQuery cohort export")
    p.add_argument("path")
    p.set_defaults(run=loadCohort)

    p = sub.add_parser("load-synthetic", help="load the hand-written fictional admissions")
    p.set_defaults(run=loadSynthetic)

    p = sub.add_parser("import-results", help="import a runPass2 results file")
    p.add_argument("path")
    p.add_argument("--model", default="medgemma", help="model the results came from")
    p.add_argument("--replace", action="store_true", help="drop an earlier import of the same file")
    p.set_defaults(run=importResults)

    p = sub.add_parser("generate", help="pre-generate documents for the first N admissions")
    p.add_argument("--n", type=int, default=10)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--mode", choices=MODES, default="sectional")
    p.add_argument("--model", default=None)
    p.add_argument("--tag", default="cli", help="label this run so it can be compared later")
    p.add_argument("--replace", action="store_true", help="drop earlier documents with the same tag")
    p.add_argument("--simplify", action="store_true", help="add the plain-language rewrite pass")
    p.add_argument("--simplify-model", default=None, help="model for the rewrite, if different")
    p.add_argument("--include-med-list", action="store_true",
                   help="let the model see the medication list (off by default in narrative modes)")
    p.add_argument("--generative", action="store_true",
                   help="have the model rewrite the doctor's instructions instead of sorting them")
    p.add_argument("--chart-only", action="store_true",
                   help="hide the doctor's own instructions and draft from the chart alone")
    p.set_defaults(run=generate)

    p = sub.add_parser("compare", help="compare tagged runs on the admissions they share")
    p.add_argument("tags", nargs="+")
    p.add_argument("--out", default=None, help="also write the tables to this CSV (plus a per-admission CSV)")
    p.set_defaults(run=compare)

    p = sub.add_parser("score-concepts", help="medical concept recall and precision for tagged runs (needs transformers)")
    p.add_argument("tags", nargs="+")
    p.add_argument("--model", default=None, help="Hugging Face token-classification model")
    p.add_argument("--force", action="store_true", help="rescore documents that already have concept scores")
    p.set_defaults(run=scoreConcepts)

    p = sub.add_parser("export", help="write a spreadsheet: EHR source, clinician text and each run, side by side")
    p.add_argument("tags", nargs="+", help="one or more tags to put next to the reference")
    p.add_argument("--n", type=int, default=None, help="only the first N shared admissions")
    p.add_argument("--out", default=None, help="output path, .xlsx or .csv (default: .xlsx next to the database)")
    p.set_defaults(run=export)

    p = sub.add_parser("review", help="write a local side-by-side page: clinician vs generated")
    p.add_argument("tags", nargs="+", help="one or more tags to show next to the reference")
    p.add_argument("--n", type=int, default=None, help="only the first N shared admissions")
    p.add_argument("--out", default=None, help="output path (default: next to the database)")
    p.add_argument("--no-open", action="store_true", help="don't open it in the browser")
    p.set_defaults(run=review)

    p = sub.add_parser("stats", help="what's in the database")
    p.set_defaults(run=stats)

    args = parser.parse_args()
    try:
        store = Store(loadSettings().dbPath)
    except StoreLocked as exc:
        sys.exit(str(exc))
    try:
        args.run(store, args)
    finally:
        store.close()


if __name__ == "__main__":
    main()
