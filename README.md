# n-sight

Patient-readable discharge instructions from the hospital record.
CIS 4914 Senior Project, University of Florida. Advisor: Dr. Mei Liu.

> **About this copy.** A snapshot of the project shared with our COIL partner
> team for course review. It contains no hospital data and no history. The app
> runs on six fictional patients (see "Run both on the fictional patients").
> Shared for review ONLY.

## What this does

For one hospital stay, n-sight builds the patient's discharge instructions
from the doctor's own written instructions, sorted into four parts: what
happened in the hospital, what to do over the next few days, when to get help
right away, and follow-up. Parts the doctor left empty are filled from the
record and labeled. Medical words get a short plain-language explanation, and
a medication list shows what changed since admission and what each medicine
is for. Automatic checks score every document (kept instructions, numbers not
in the record, reading level) against the doctor's original text.

## Data

MIMIC-IV, accessed under the PhysioNet Credentialed Data Use Agreement. Every
team member needs their own CITI training and signed DUA. No clinical data is
committed to this repo, and no data leaves the local environment. All models
are open-weight and run on-premises.

## Layout

    src/nsight/ingest      clean, segment, normalize codes
    src/nsight/graph       Neo4j patient graph
    src/nsight/retrieve    audience-conditioned retrieval, safety floor
    src/nsight/generate    prompts and model client
    src/nsight/evaluate    metrics and verification
    src/nsight/api         FastAPI service
    ui/                    React review interface
    tests/                 pytest, including the answer-key leak test

## Setup

    python -m venv .venv
    .venv\Scripts\activate
    pip install -r requirements.txt
    python -m nltk.downloader cmudict
    pytest

The cmudict download is one time. Reading-grade scores need it, and without a
local copy textstat tries to fetch it at runtime.

## Run the backend

Data stays outside the repo. Load the cohort export into the local database
(`data/interim/nsight.duckdb`, gitignored), then pull in earlier results so the
app opens on finished documents:

    $env:PYTHONPATH = "src"
    python -m nsight.cli load-cohort D:\MIMIC-IV\cohortV2.json
    python -m nsight.cli import-results D:\MIMIC-IV\pass10_medgemma_all.json --model medgemma
    python -m nsight.cli generate --n 10 --mode sectional
    python -m nsight.cli stats

Only one process can write to the database, so stop the API before running
these. `generate` needs Ollama running with the model pulled.

Start the API (localhost only):

    uvicorn --app-dir src nsight.api.main:app --host 127.0.0.1 --port 8000

Interactive docs are at http://127.0.0.1:8000/docs.

| Endpoint | What it returns |
|---|---|
| `GET /health` | API status, whether Ollama is reachable, installed models, admissions loaded |
| `GET /admissions?search=&limit=&offset=` | Patient list. Admissions flagged by the leak check are hidden unless `includeLeaks=true` |
| `GET /admissions/{hadmId}` | Diagnoses, medications (original and plain language), allergies, the note the model sees, and the clinician's instructions for comparison |
| `GET /admissions/{hadmId}/documents` | Every document generated for the admission, newest first |
| `POST /admissions/{hadmId}/documents` | Generate a new document. Body: `{"mode": "sectional"}`. Takes about a minute on a 4B model |
| `GET /documents/{id}` | One document with its sections, medication list, scores, and warnings |
| `GET /stats` | Per-mode metrics across the latest document for each admission |
| `GET /patients/{patient_id}/health` | For the patient's latest admission: vitals read from the note's exam (discharge exam first, admission exam labeled as such), MedlinePlus topics for their diagnoses split into their own questions, and each discharge medicine's side effects with the serious ones a patient can notice grouped first and the rest kept in full. Reads `src/nsight/FAQ/faq_data` (or `NSIGHT_FAQ_DIR`) |
| `GET /patients/{patient_id}/interactions` | Provider view only. Pairs of the patient's medicines that DrugBank lists an interaction for. DrugBank gives no severity, so these aren't shown to patients |
| `GET /patients/{patient_id}/encounters/{encounter_id}/terms` | Where the patient's own conditions first appear in the instructions (section, item, character offsets), for pop-ups with the MedlinePlus summary. Everyday words like pain and fever are skipped |
| `GET /runs` | Every tagged run with its size and model, plus the run the dashboard shows |
| `GET /runs/compare?tags=a&tags=b` | Mean of each check per run over the admissions they share, with paired sign tests against the first run. Same numbers as `nsight.cli compare` |
| `GET /patients?search=&specialty=` | One row per patient (MIMIC subject) with their latest encounter, for the provider dashboard. `search` takes a patient or encounter ID prefix, or words from a diagnosis. `specialty` (see `/specialties`) keeps patients with an encounter in that field. With either filter, `matches` lists each matching encounter and why it matched |
| `GET /specialties` | Specialties the case search knows. Nephrology so far: kidney diagnoses, kidney medicines (sevelamer, cinacalcet, ...), or dialysis, transplant or CKD in the past medical history. Add one in `src/nsight/api/specialties.py` |
| `GET /patients/{patient_id}` | A patient and all their encounters (admissions), newest first |
| `GET /patients/{patient_id}/encounters/{encounter_id}?glossary=` | One encounter: the accessible summary and instruction sections from the latest generated document, the medication list with what each medicine is for, what changed since admission (start, stop, changed dose), allergies, the clinician's original instructions, and the source note. Each section also has `rich_items`: the item text without the explanations written in, plus spans (UTF-16 offsets) for `term` (with its explanation), `removed` (a de-identified name, date, phone number or detail) and `condition` (a MedlinePlus topic). The text is plain, never markup. `reason_plain` gives the first diagnosis in plain words, and drug names drop pharmacy tall-man capitals. `glossary=separate` (the default, or `NSIGHT_GLOSSARY_STYLE`) puts each medical word's explanation on its own line after the item; `glossary=inline` keeps it in parentheses after the word. Both stay until user testing picks one. Either way, de-identified details read as "[date on your paperwork]" and so on, not "[redacted]" |

Modes are `allText`, `structured`, `templated`, and `sectional`. In `templated`
and `sectional` the medication list and allergies are copied from the record,
translated from pharmacy shorthand, and never generated. By default the model
doesn't see the medication list in those modes; pass `"includeMedList": true`
to compare.

Settings can go in a `.env` file at the repo root:

    NSIGHT_DB=data/interim/nsight.duckdb
    NSIGHT_MODEL=medgemma
    OLLAMA_URL=http://127.0.0.1:11434
    NSIGHT_NUM_CTX=16384
    NSIGHT_DOC_SOURCE=final100

`NSIGHT_DOC_SOURCE` picks which tagged run the patient dashboard shows. Without
it, each encounter shows its newest document.

## Compare runs

Tag each run, then compare tags on the admissions they share. Every mean comes
with a 95% bootstrap interval. Each run is compared to the first with the mean
paired difference and its interval, how many admissions got better or worse, an
exact sign test, and a Wilcoxon signed-rank test.

    python -m nsight.cli generate --n 100 --tag med-base --replace
    python -m nsight.cli generate --n 100 --model gemma3:4b --tag gemma-base --replace
    python -m nsight.cli generate --n 100 --simplify --tag med-simple --replace
    python -m nsight.cli compare med-base gemma-base med-simple

Concept recall and precision need a second pass. A biomedical NER model
(`d4data/biomedical-ner-all`, downloaded once from Hugging Face, runs on the GPU
when there is one) pulls medicines, conditions, symptoms, tests and procedures
from the doctor's instructions, the record, and each summary:

    python -m nsight.cli score-concepts plain100 base100

- concept recall: share of the doctor's medical concepts the summary still mentions
- concept precision: share of the summary's medical concepts found in the record
  (fixed warning-sign text and glossary explanations are left out)

Readability is scored four ways: Flesch-Kincaid, SMOG, Dale-Chall, and the share
of unfamiliar words, plus unexplained abbreviations per 100 words.

Faithfulness metrics are cheap proxies, not verification:

- unsupported numbers: numbers in the narrative that appear nowhere in the record
- speculative sentences: guesses about causes, or suggested testing the record doesn't contain

`--simplify` rewrites each section in plain language. A rewrite is thrown out,
and the original kept, if it loses any number, the patient's drug or allergy
names, or a proper noun, or if it isn't actually easier to read.

## Run the React client

    cd ui
    npm install --legacy-peer-deps
    npm run dev

Open http://localhost:5173. The provider dashboard lists patients from the
database; clicking one opens their encounters. An encounter with no generated
document shows a button that runs the pipeline on it (needs Ollama).

## Run both on the fictional patients

The six hand-written cases need no MIMIC access, so this is the quickest way to
see the whole app working. Two terminals from the repo root:

    $env:PYTHONPATH = "src"
    $env:NSIGHT_DB = "data/interim/synthetic.duckdb"
    python -m nsight.cli load-synthetic
    python -m nsight.cli generate --n 6 --model gemma3:4b --tag demo
    python -m uvicorn --app-dir src nsight.api.main:app --host 127.0.0.1 --port 8000

    cd ui
    npm run dev

Skip `generate` to start with no documents and make them from the UI instead.
Generating needs [Ollama](https://ollama.com) running with `gemma3:4b` pulled.
Open http://localhost:5173/patient/90000002 for the first fictional patient.

When a backend route or Pydantic model changes:

1. Start the API so `/openapi.json` is available.
2. From `ui/`, run `npm run generate:api`.
3. Add or update the feature function under `ui/src/api/features`.
4. Add query options or a hook under `ui/src/api/queries.ts` when React needs the data.
