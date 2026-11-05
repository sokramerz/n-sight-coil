"""n-sight API. Binds to localhost only; nothing here should be reachable off the machine."""
from __future__ import annotations

import json
import statistics
from dataclasses import asdict
import threading
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from nsight.api.healthinfo import HealthInfo
from nsight.api.patients import Encounter, Patient, PatientSummary, StorePatientRepository
from nsight.api.specialties import SPECIALTIES
from nsight.api.schemas import (AdmissionDetail, AdmissionPage, AdmissionSummary,
                                DocumentOut, DocumentScore, DocumentSection,
                                GenerateRequest, HealthResponse, Medication, MetricRow, ModeStats,
                                PairedRow, PatientHealth, PatientInteractions, RunComparison, RunInfo, RunList,
                                SpecialtyOption, StatsResponse, TermLink, VitalSigns)
from nsight.config import loadSettings
from nsight.db import Store, rowToRecord, toList
from nsight.evaluate.compare import METRICS, MissingRun, compareRuns, listRuns
from nsight.evaluate.metrics import READING_TARGET
from nsight.generate.model_client import ModelUnavailable, OllamaClient
from nsight.generate.pipeline import GenerationFailed, generateDocument
from nsight.ingest.cleaning import stripPlaceholders
from nsight.ingest.medications import allergyLines, parseMedicationEntries
from nsight.ingest.vitals import vitalSigns

state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = loadSettings()
    state["settings"] = settings
    state["store"] = Store(settings.dbPath)
    state["client"] = OllamaClient(settings)
    state["healthInfo"] = HealthInfo()
    state["patients"] = StorePatientRepository(state["store"], healthInfo=state["healthInfo"])
    # the drug files take a couple of seconds to parse; do it before the first Health tab opens
    threading.Thread(target=state["healthInfo"].warm, daemon=True).start()
    yield
    state["store"].close()


app = FastAPI(title="n-sight", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:4173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def getStore() -> Store:
    return state["store"]


def getClient() -> OllamaClient:
    return state["client"]


def getPatients() -> StorePatientRepository:
    return state["patients"]


def getHealthInfo() -> HealthInfo:
    return state["healthInfo"]


HEALTH_SOURCES = [
    "Drug interactions and side effects: the project's drug knowledge graph, built on DrugBank (go.drugbank.com)",
    "Health topics: MedlinePlus, U.S. National Library of Medicine (medlineplus.gov)",
]


def toSummary(row: dict) -> AdmissionSummary:
    diagnoses = toList(row.get("diagnoses"))
    return AdmissionSummary(
        hadmId=row["hadm_id"],
        subjectId=row.get("subject_id"),
        service=row.get("service"),
        admitTime=row.get("admit_time") or None,
        dischargeTime=row.get("disch_time") or None,
        lengthOfStayDays=row.get("los_days"),
        primaryDiagnosis=diagnoses[0] if diagnoses else None,
        medicationCount=row.get("med_count") or 0,
        highRiskCount=row.get("high_risk_count") or 0,
        allergyCount=row.get("allergy_count") or 0,
        documentCount=row.get("doc_count") or 0,
        leaks=bool(row.get("leaks")),
    )


@lru_cache(maxsize=512)
def medicationsFor(section: str | None) -> tuple[Medication, ...]:
    return tuple(
        Medication(index=m.index, name=m.name, original=m.original, plain=m.plain, highRisk=m.highRisk, kind=m.kind)
        for m in parseMedicationEntries(section)
    )


def toDocument(row: dict, admission: dict) -> DocumentOut:
    return DocumentOut(
        id=row["id"],
        hadmId=row["hadm_id"],
        mode=row["mode"],
        model=row["model"],
        includeMedList=bool(row["include_med_list"]),
        source=row["source"],
        createdAt=row["created_at"].isoformat() if row.get("created_at") else "",
        narrative=row["narrative"] or "",
        sections=[DocumentSection(**s) for s in json.loads(row["sections"] or "[]")],
        medications=list(medicationsFor(admission["meds_section"])),
        allergies=allergyLines(admission["allergies_section"]),
        document=row["document"] or "",
        score=DocumentScore.model_validate(json.loads(row["score"])),
        warnings=json.loads(row["warnings"] or "[]"),
        dosingSentencesRemoved=row.get("removed") or 0,
        promptTokens=row.get("prompt_tokens") or 0,
        durationMs=row.get("duration_ms") or 0,
    )


def requireAdmission(store: Store, hadmId: int) -> dict:
    admission = store.getAdmission(hadmId)
    if admission is None:
        raise HTTPException(404, f"admission {hadmId} not found")
    return admission


@app.get("/health", response_model=HealthResponse)
def health(store: Store = Depends(getStore), client: OllamaClient = Depends(getClient)):
    try:
        models, reachable = client.listModels(), True
    except ModelUnavailable:
        models, reachable = [], False
    return HealthResponse(status="ok", ollamaReachable=reachable,
                          defaultModel=client.settings.model, installedModels=models,
                          admissionsLoaded=store.countAdmissions())


@app.get("/admissions", response_model=AdmissionPage)
def listAdmissions(search: str = "", limit: int = Query(50, ge=1, le=500),
                   offset: int = Query(0, ge=0), includeLeaks: bool = False,
                   store: Store = Depends(getStore)):
    rows, total = store.listAdmissions(search.strip(), limit, offset, includeLeaks)
    return AdmissionPage(items=[toSummary(r) for r in rows], total=total, limit=limit, offset=offset)


@app.get("/admissions/{hadmId}", response_model=AdmissionDetail)
def getAdmission(hadmId: int, store: Store = Depends(getStore)):
    row = requireAdmission(store, hadmId)
    return AdmissionDetail(
        **toSummary(row).model_dump(),
        diagnoses=toList(row["diagnoses"]),
        medications=list(medicationsFor(row["meds_section"])),
        allergies=allergyLines(row["allergies_section"]),
        disposition=stripPlaceholders(row["disposition_section"]) or None,
        sourceNote=stripPlaceholders(row["model_input"]),
        clinicianInstructions=stripPlaceholders(row["ref_instructions"]) or None,
    )


@app.get("/admissions/{hadmId}/documents", response_model=list[DocumentOut])
def listDocuments(hadmId: int, store: Store = Depends(getStore)):
    admission = requireAdmission(store, hadmId)
    return [toDocument(r, admission) for r in store.listDocuments(hadmId)]


@app.post("/admissions/{hadmId}/documents", response_model=DocumentOut, status_code=201)
def generate(hadmId: int, body: GenerateRequest, store: Store = Depends(getStore),
             client: OllamaClient = Depends(getClient)):
    """Generate a new document. Runs the model synchronously; expect around a minute on a 4B model."""
    admission = requireAdmission(store, hadmId)
    try:
        result = generateDocument(rowToRecord(admission), client, mode=body.mode,
                                  model=body.model, includeMedList=body.includeMedList,
                                  simplify=body.simplify, simplifyModel=body.simplifyModel,
                                  useInstructions=body.useInstructions, generative=body.generative)
    except ModelUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except GenerationFailed as exc:
        raise HTTPException(502, str(exc)) from exc
    docId = store.addDocument(hadmId, result, source="live")
    return toDocument(store.getDocument(docId), admission)


@app.get("/documents/{docId}", response_model=DocumentOut)
def getDocument(docId: int, store: Store = Depends(getStore)):
    row = store.getDocument(docId)
    if row is None:
        raise HTTPException(404, f"document {docId} not found")
    return toDocument(row, requireAdmission(store, row["hadm_id"]))


@app.get("/patients", response_model=list[PatientSummary])
def listPatients(search: str | None = Query(None, description="Patient or encounter ID (prefix), or words in a diagnosis"),
                 specialty: str | None = Query(None, description="A key from /specialties, e.g. nephrology"),
                 repo: StorePatientRepository = Depends(getPatients)):
    if specialty and specialty not in SPECIALTIES:
        raise HTTPException(422, f"Unknown specialty. Choose from: {', '.join(SPECIALTIES)}")
    return repo.list_patients(search=search, specialty=specialty)


@app.get("/specialties", response_model=list[SpecialtyOption])
def specialties():
    return [SpecialtyOption(key=key, label=rule.label) for key, rule in SPECIALTIES.items()]


@app.get("/patients/{patient_id}", response_model=Patient)
def getPatient(patient_id: str, repo: StorePatientRepository = Depends(getPatients)):
    patient = repo.get_patient(patient_id)
    if patient is None:
        raise HTTPException(404, "Patient not found")
    return patient


@app.get("/patients/{patient_id}/encounters/{encounter_id}", response_model=Encounter)
def getEncounter(patient_id: str, encounter_id: str,
                 glossary: Literal["separate", "inline"] | None = Query(
                     None, description="How medical words are explained; defaults to NSIGHT_GLOSSARY_STYLE"),
                 repo: StorePatientRepository = Depends(getPatients)):
    encounter = repo.get_encounter(patient_id, encounter_id, glossary)
    if encounter is None:
        raise HTTPException(404, "Encounter not found")
    return encounter


def latestAdmission(patient_id: str, repo: StorePatientRepository) -> dict:
    rows = repo.admissionRows(int(patient_id)) if patient_id.isdigit() else []
    if not rows:
        raise HTTPException(404, "Patient not found")
    return rows[0]


def medicineNames(row: dict) -> list[str]:
    return [m.name for m in parseMedicationEntries(row.get("meds_section")) if m.kind == "med"]


@app.get("/patients/{patient_id}/health", response_model=PatientHealth)
def patientHealth(patient_id: str, repo: StorePatientRepository = Depends(getPatients),
                  info: HealthInfo = Depends(getHealthInfo)):
    """Vitals, condition topics and medicine side effects for the patient's most recent admission."""
    latest = latestAdmission(patient_id, repo)
    vitals = vitalSigns(latest.get("model_input"))
    return PatientHealth(
        encounterId=str(latest["hadm_id"]),
        available=info.available,
        vitals=VitalSigns(**asdict(vitals)) if vitals else None,
        medicines=info.medicines(medicineNames(latest)),
        topics=info.topics(toList(latest.get("diagnoses"))),
        sources=HEALTH_SOURCES,
    )


@app.get("/patients/{patient_id}/interactions", response_model=PatientInteractions)
def patientInteractions(patient_id: str, repo: StorePatientRepository = Depends(getPatients),
                        info: HealthInfo = Depends(getHealthInfo)):
    """For the provider view only: DrugBank gives no severity, so these aren't shown to patients."""
    latest = latestAdmission(patient_id, repo)
    return PatientInteractions(
        encounterId=str(latest["hadm_id"]),
        interactions=info.interactions(medicineNames(latest)),
        note="Listed in DrugBank. No severity is given, and many listed pairs are routinely prescribed together.",
    )


@app.get("/patients/{patient_id}/encounters/{encounter_id}/terms", response_model=list[TermLink])
def encounterTerms(patient_id: str, encounter_id: str, repo: StorePatientRepository = Depends(getPatients),
                   info: HealthInfo = Depends(getHealthInfo)):
    """Where the patient's conditions first appear in the instructions, for pop-ups with the MedlinePlus summary."""
    encounter = repo.get_encounter(patient_id, encounter_id)
    if encounter is None:
        raise HTTPException(404, "Encounter not found")
    row = next(r for r in repo.admissionRows(int(patient_id)) if str(r["hadm_id"]) == encounter_id)
    return info.termLinks([s.items for s in encounter.sections], toList(row.get("diagnoses")))


@app.get("/runs", response_model=RunList)
def runs(store: Store = Depends(getStore), repo: StorePatientRepository = Depends(getPatients)):
    rows = listRuns(store)
    tags = [r["tag"] for r in rows]
    default = repo.documentSource if repo.documentSource in tags else (tags[0] if tags else None)
    return RunList(runs=[RunInfo(tag=r["tag"], admissions=r["admissions"], model=r["model"],
                                 lastRun=r["lastRun"].isoformat() if r["lastRun"] else None) for r in rows],
                   defaultRun=default)


@app.get("/runs/compare", response_model=RunComparison)
def compareRunsRoute(tags: list[str] = Query(..., min_length=1, max_length=4), store: Store = Depends(getStore)):
    """Means per run over the admissions every run shares, and paired sign tests against the first run."""
    try:
        result = compareRuns(store, tags)
    except MissingRun as exc:
        raise HTTPException(404, str(exc)) from exc
    higher = {label: better for label, _, better in METRICS}
    return RunComparison(
        tags=tags, admissions=len(result.shared), clinicianGrade=result.clinicianGrade,
        metrics=[MetricRow(label=label, higherIsBetter=higher[label], values=values,
                           ci={tag: list(ci) if ci else None for tag, ci in result.cis[label].items()})
                 for label, values in result.means.items()],
        paired=[PairedRow(run=row.run, label=row.label, better=row.better, worse=row.worse, tied=row.tied, p=row.p,
                          wilcoxonP=row.wilcoxonP, difference=row.difference,
                          differenceCi=list(row.differenceCi) if row.differenceCi else None)
                for row in result.paired],
    )


@app.get("/stats", response_model=StatsResponse)
def stats(store: Store = Depends(getStore)):
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in store.documentScores():
        score = json.loads(row["score"])
        # count what the model wrote, not what survived the dosing stripper
        score["restated"] = bool(score["medRestatements"] or row["removed"])
        model = row["model"].removesuffix(":latest")
        groups.setdefault((row["mode"], model), []).append(score)
    modes = []
    for (mode, model), scores in sorted(groups.items()):
        withRisk = [s for s in scores if s["highRiskTotal"]]
        grades = [s["readingGrade"] for s in scores if s["readingGrade"] is not None]
        modes.append(ModeStats(
            mode=mode, model=model, documents=len(scores),
            medRecall=round(statistics.mean(s["medRecall"] for s in scores), 3),
            allergyRecall=round(statistics.mean(s["allergyRecall"] for s in scores), 3),
            highRiskComplete=sum(1 for s in withRisk if not s["highRiskMissing"]),
            highRiskAdmissions=len(withRisk),
            readingGrade=round(statistics.mean(grades), 1) if grades else None,
            patientVoice=round(statistics.mean(s["patientVoice"] for s in scores), 2),
            followedAllSections=sum(1 for s in scores if s["sections"] == 4),
            unsupportedNumbers=sum(1 for s in scores if s.get("unsupportedNumbers")),
            speculative=sum(1 for s in scores if s.get("speculative")),
            loops=sum(1 for s in scores if s["degenerate"]),
            restated=sum(1 for s in scores if s["restated"]),
        ))
    return StatsResponse(readingTarget=READING_TARGET, modes=modes)
