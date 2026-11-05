"""Side-by-side review page: the clinician's discharge instructions next to generated ones.

The page is written under data/interim, which is gitignored, and opened from disk.
It holds MIMIC note text, so it must never be committed, uploaded, or shared.
"""

from __future__ import annotations

import html
import json
import re

from nsight.db import Store, rowToRecord
from nsight.evaluate.metrics import SPECULATION, instructionCoverage, readingGrade, sourceText, unsupportedNumbers

SHOWN_METRICS = (("strategy", "built by"), ("instructionCoverage", "doctor's items"), ("draftCoverage", "before rewrite"), ("readingGrade", "grade"), ("patientVoice", "voice"),
                 ("unsupportedNumbers", "numbers"), ("speculative", "speculative"),
                 ("simplifiedSections", "simplified"))

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>n-sight review</title>
<style>
:root {{ --bg:#f6f6f4; --card:#fff; --ink:#1d1d1b; --muted:#6b6b66; --line:#deded8;
        --num:#ffd9a8; --spec:#d9e4ff; --accent:#2b5fab; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#18181a; --card:#222225; --ink:#e8e8e4; --muted:#9a9a94; --line:#38383c;
          --num:#7a4b12; --spec:#26406e; --accent:#8db3f0; }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink);
       font:15px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }}
header {{ position:sticky; top:0; z-index:2; background:var(--bg); border-bottom:1px solid var(--line);
         padding:12px 20px; display:flex; gap:16px; align-items:center; flex-wrap:wrap; }}
header h1 {{ font-size:17px; margin:0; }}
header .legend span {{ padding:1px 6px; border-radius:3px; margin-right:6px; font-size:13px; }}
nav {{ display:flex; gap:6px; flex-wrap:wrap; }}
nav a {{ font-size:13px; color:var(--accent); text-decoration:none; padding:2px 6px;
        border:1px solid var(--line); border-radius:4px; }}
button {{ font:inherit; font-size:13px; padding:4px 10px; border:1px solid var(--line);
         background:var(--card); color:var(--ink); border-radius:4px; cursor:pointer; }}
main {{ padding:16px 20px 60px; }}
section.adm {{ background:var(--card); border:1px solid var(--line); border-radius:8px;
              padding:16px; margin-bottom:24px; }}
section.adm h2 {{ font-size:16px; margin:0 0 4px; }}
.dx {{ color:var(--muted); font-size:13px; margin-bottom:10px; }}
.cols {{ display:grid; grid-template-columns:repeat({cols}, minmax(0,1fr)); gap:14px; }}
@media (max-width:900px) {{ .cols {{ grid-template-columns:1fr; }} }}
.col h3 {{ font-size:13px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted);
          margin:0 0 4px; }}
.metrics {{ font-size:12px; color:var(--muted); margin-bottom:6px; min-height:3em; }}
.text {{ white-space:pre-wrap; border-top:1px solid var(--line); padding-top:8px; }}
.warn {{ font-size:12px; color:#b4561b; margin-top:8px; }}
mark.num {{ background:var(--num); color:inherit; }}
mark.spec {{ background:var(--spec); color:inherit; }}
details {{ margin-top:12px; font-size:13px; }}
details pre {{ white-space:pre-wrap; max-height:420px; overflow:auto; background:var(--bg);
              padding:10px; border-radius:6px; }}
textarea {{ width:100%; min-height:70px; margin-top:12px; font:inherit; font-size:14px;
           background:var(--bg); color:var(--ink); border:1px solid var(--line); border-radius:6px;
           padding:8px; }}
</style></head><body>
<header>
  <h1>n-sight review</h1>
  <div class="legend"><span style="background:var(--num)">number not in record</span>
    <span style="background:var(--spec)">speculative wording</span></div>
  <button id="export">Export notes (CSV)</button>
  <nav>{nav}</nav>
</header>
<main>{body}</main>
<script>
const key = "nsight-review-notes";
let notes = {{}};
try {{ notes = JSON.parse(localStorage.getItem(key) || "{{}}"); }} catch (e) {{}}
document.querySelectorAll("textarea[data-id]").forEach(t => {{
  t.value = notes[t.dataset.id] || "";
  t.addEventListener("input", () => {{
    notes[t.dataset.id] = t.value;
    try {{ localStorage.setItem(key, JSON.stringify(notes)); }} catch (e) {{}}
  }});
}});
document.getElementById("export").onclick = () => {{
  const rows = [["hadm_id", "notes"]];
  document.querySelectorAll("textarea[data-id]").forEach(t => rows.push([t.dataset.id, t.value]));
  const csv = rows.map(r => r.map(v => '"' + String(v).replace(/"/g, '""') + '"').join(",")).join("\\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], {{ type: "text/csv" }}));
  a.download = "review-notes.csv";
  a.click();
}};
</script></body></html>"""


HEADING = re.compile(r"^(?:[A-Z][^\n:]{2,60}:|YOUR [A-Z ]+)$", re.MULTILINE)


def highlight(text: str, numbers: list[str]) -> str:
    out = html.escape(text or "")
    out = HEADING.sub(lambda m: f"<b>{m.group(0)}</b>", out)
    out = SPECULATION.sub(lambda m: f'<mark class="spec">{m.group(0)}</mark>', out)
    for n in sorted(numbers, key=len, reverse=True):
        out = re.sub(rf"(?<![\w.]){re.escape(n)}(?![\w]|\.\d)", f'<mark class="num">{n}</mark>', out)
    return out


def latestByTag(store: Store, tag: str) -> dict[int, dict]:
    rows = store.query("""SELECT * FROM (
        SELECT *, row_number() OVER (PARTITION BY hadm_id ORDER BY id DESC) AS rn
        FROM documents WHERE source = ?) WHERE rn = 1""", [tag])
    return {r["hadm_id"]: r for r in rows}


def metricLine(score: dict) -> str:
    parts = []
    for key, label in SHOWN_METRICS:
        value = score.get(key)
        if value is None:
            continue
        if isinstance(value, list):
            value = len(value)
        if key == "strategy":
            parts.append({"extract": "sorting doctor's text", "generate": "model writing"}.get(value, value))
            continue
        if key == "simplifiedSections" and not value and not score.get("simplifyRejected"):
            continue
        parts.append(f"{label} {round(value, 2) if isinstance(value, float) else value}")
    return " · ".join(parts)


def buildReview(store: Store, tags: list[str], limit: int | None = None) -> tuple[str, int]:
    runs = {tag: latestByTag(store, tag) for tag in tags}
    missing = [t for t, docs in runs.items() if not docs]
    if missing:
        raise ValueError(f"no documents tagged {', '.join(missing)}")
    shared = sorted(set.intersection(*(set(d) for d in runs.values())))[:limit]

    nav, body = [], []
    for hadmId in shared:
        row = store.getAdmission(hadmId)
        if not row:
            continue
        record = rowToRecord(row)
        diagnoses = ", ".join(record["dischargeDiagnoses"][:5])
        refGrade = readingGrade(record["refInstructions"])
        cols = ['<div class="col"><h3>Clinician (reference)</h3>'
                f'<div class="metrics">{"grade " + str(refGrade) if refGrade is not None else ""}</div>'
                f'<div class="text">{html.escape(record["refInstructions"] or "(none)")}</div></div>']
        for tag in tags:
            doc = runs[tag][hadmId]
            score = json.loads(doc["score"] or "{}")
            text = doc["document"] or ""
            if "instructionCoverage" not in score:
                items, missed = instructionCoverage(record, text)
                score["instructionCoverage"] = round(1 - len(missed) / items, 2) if items else None
                score["missedInstructions"] = missed
            numbers = score.get("unsupportedNumbers")
            if numbers is None:
                numbers = unsupportedNumbers(doc["narrative"], sourceText(record))
            warnings = json.loads(doc["warnings"] or "[]")
            if score.get("missedInstructions") and not any("doctor's instructions" in w for w in warnings):
                warnings.append("not carried over from the doctor's instructions: " + ", ".join(score["missedInstructions"]))
            warn = "".join(f'<div class="warn">{html.escape(w)}</div>' for w in warnings)
            cols.append(f'<div class="col"><h3>{html.escape(tag)} · {html.escape(doc["model"])}</h3>'
                        f'<div class="metrics">{html.escape(metricLine(score))}</div>'
                        f'<div class="text">{highlight(text, numbers)}</div>'
                        f'{warn}</div>')
        nav.append(f'<a href="#h{hadmId}">{hadmId}</a>')
        body.append(
            f'<section class="adm" id="h{hadmId}"><h2>{hadmId}</h2>'
            f'<div class="dx">{html.escape(diagnoses)}</div>'
            f'<div class="cols">{"".join(cols)}</div>'
            f'<details><summary>Source the model saw</summary><pre>{html.escape(record["modelInput"] or "")}</pre></details>'
            f'<textarea data-id="{hadmId}" placeholder="Notes on this admission"></textarea></section>')
    page = PAGE.format(cols=len(tags) + 1, nav="".join(nav), body="".join(body))
    return page, len(body)


EXCEL_CELL_LIMIT = 32000


def fitCell(text: str) -> str:
    text = text or ""
    return text if len(text) <= EXCEL_CELL_LIMIT else text[:EXCEL_CELL_LIMIT] + "\n[cut to fit an Excel cell]"


def exportRows(store: Store, tags: list[str], limit: int | None = None) -> tuple[list[str], list[list]]:
    """One row per admission: the chart the model saw, the clinician's text, and each run's document."""
    runs = {tag: latestByTag(store, tag) for tag in tags}
    missing = [t for t, docs in runs.items() if not docs]
    if missing:
        raise ValueError(f"no documents tagged {', '.join(missing)}")
    shared = sorted(set.intersection(*(set(d) for d in runs.values())))[:limit]

    header = ["hadm_id", "diagnoses", "EHR source (what the model saw)", "clinician instructions",
              "clinician grade"]
    for tag in tags:
        header += [f"{tag} document", f"{tag} built by", f"{tag} doctor's items covered", f"{tag} grade",
                   f"{tag} unsupported numbers", f"{tag} speculative", f"{tag} warnings"]
    rows = []
    for hadmId in shared:
        row = store.getAdmission(hadmId)
        if not row:
            continue
        record = rowToRecord(row)
        out = [hadmId, ", ".join(record["dischargeDiagnoses"]), fitCell(record["modelInput"]),
               fitCell(record["refInstructions"]), readingGrade(record["refInstructions"])]
        for tag in tags:
            doc = runs[tag][hadmId]
            score = json.loads(doc["score"] or "{}")
            if "instructionCoverage" not in score:
                items, missed = instructionCoverage(record, doc["document"] or "")
                score["instructionCoverage"] = round(1 - len(missed) / items, 2) if items else None
            out += [fitCell(doc["document"]), score.get("strategy", ""), score.get("instructionCoverage"),
                    score.get("readingGrade"), ", ".join(score.get("unsupportedNumbers") or []),
                    score.get("speculative", 0), "\n".join(json.loads(doc["warnings"] or "[]"))]
        rows.append(out)
    return header, rows


def writeExport(path, header: list[str], rows: list[list]) -> str:
    """An .xlsx with wrapped text columns, or a CSV that Excel opens with the right encoding."""
    from pathlib import Path
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".xlsx":
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Alignment, Font
        except ImportError:
            path = path.with_suffix(".csv")
        else:
            book = Workbook()
            sheet = book.active
            sheet.title = "side by side"
            sheet.append(header)
            for row in rows:
                sheet.append(row)
            wrap = Alignment(wrap_text=True, vertical="top")
            for col in sheet.iter_cols(min_row=1, max_row=sheet.max_row):
                letter = col[0].column_letter
                isText = any(word in col[0].value for word in ("document", "source", "instructions", "warnings",
                                                               "diagnoses"))
                sheet.column_dimensions[letter].width = 70 if isText else 14
                for cell in col:
                    cell.alignment = wrap
                col[0].font = Font(bold=True)
            sheet.freeze_panes = "C2"
            book.save(path)
            return str(path)
    import csv
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    return str(path)

