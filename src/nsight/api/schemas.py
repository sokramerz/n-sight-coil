"""Response and request models. The front end generates its TypeScript types from these."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Mode = Literal["allText", "structured", "templated", "sectional"]


class HealthResponse(BaseModel):
    status: str
    ollamaReachable: bool
    defaultModel: str
    installedModels: list[str]
    admissionsLoaded: int


class AdmissionSummary(BaseModel):
    hadmId: int
    subjectId: int | None
    service: str | None
    admitTime: str | None
    dischargeTime: str | None
    lengthOfStayDays: int | None
    primaryDiagnosis: str | None
    medicationCount: int
    highRiskCount: int
    allergyCount: int
    documentCount: int
    leaks: bool


class AdmissionPage(BaseModel):
    items: list[AdmissionSummary]
    total: int
    limit: int
    offset: int


class Medication(BaseModel):
    index: int
    name: str
    original: str = Field(description="Line as written in the discharge medication list")
    plain: str = Field(description="Same line with pharmacy shorthand in plain language")
    highRisk: bool
    kind: str = Field("med", description="'med', or 'order' for labs, therapy and equipment")


class AdmissionDetail(AdmissionSummary):
    diagnoses: list[str]
    medications: list[Medication]
    allergies: list[str]
    disposition: str | None
    sourceNote: str = Field(description="Note text the model is allowed to see")
    clinicianInstructions: str | None = Field(
        description="What the clinician wrote; held out from the model, shown for comparison")


class DocumentSection(BaseModel):
    header: str | None
    text: str


class DocumentScore(BaseModel):
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
    unsupportedNumbers: list[str] = Field(default_factory=list,
                                          description="Numbers in the narrative that appear nowhere in the record")
    speculative: int = Field(0, description="Sentences that guess at causes or suggest further testing")
    simplifiedSections: int = 0
    simplifyRejected: int = Field(0, description="Simplified sections discarded because they dropped or added a fact")
    simplifyReasons: dict[str, int] = Field(default_factory=dict,
                                            description="Failed rewrite checks by kind, counted over every attempt")
    missingMeds: list[str]
    missingHighRisk: list[str]
    fromInstructions: bool = Field(False, description="Built on the doctor's own patient instructions")
    instructionItems: int = Field(0, description="Action items found in the doctor's instructions")
    instructionCoverage: float | None = Field(None, description="Share of those items the document carries")
    missedInstructions: list[str] = Field(default_factory=list)
    draftCoverage: float | None = Field(None, description="Coverage before the plain-language rewrite")
    conflicts: list[str] = Field(default_factory=list, description="Course lengths that contradict the record")
    strategy: str = Field("generate", description="'extract' sorts the doctor's sentences; 'generate' writes")
    explainedTerms: list[str] = Field(default_factory=list,
                                      description="Abbreviations and medical words given a plain explanation")
    filledSections: list[str] = Field(default_factory=list,
                                      description="Sections the doctor left empty, filled from elsewhere in the record")


class DocumentOut(BaseModel):
    id: int
    hadmId: int
    mode: str
    model: str
    includeMedList: bool
    source: str
    createdAt: str
    narrative: str
    sections: list[DocumentSection]
    medications: list[Medication]
    allergies: list[str]
    document: str
    score: DocumentScore
    warnings: list[str]
    dosingSentencesRemoved: int
    promptTokens: int
    durationMs: int


class GenerateRequest(BaseModel):
    mode: Mode = "sectional"
    model: str | None = None
    includeMedList: bool | None = Field(
        default=None, description="Defaults to false for templated and sectional")
    simplify: bool = Field(False, description="Rewrite each section in plain language, keeping every fact")
    simplifyModel: str | None = None
    useInstructions: bool = Field(True, description="Build on the doctor's own patient instructions")
    generative: bool = Field(False, description="Rewrite the doctor's instructions instead of sorting them")


class ModeStats(BaseModel):
    mode: str
    model: str
    documents: int
    medRecall: float
    allergyRecall: float
    highRiskComplete: int
    highRiskAdmissions: int
    readingGrade: float | None
    patientVoice: float
    followedAllSections: int
    unsupportedNumbers: int = Field(0, description="Documents with a number not found in the record")
    speculative: int = Field(0, description="Documents with at least one speculative sentence")
    loops: int
    restated: int = Field(description="Documents where the model restated medication dosing, "
                                      "counted before the dosing stripper ran")


class StatsResponse(BaseModel):
    readingTarget: float
    modes: list[ModeStats]


class RunInfo(BaseModel):
    tag: str
    admissions: int
    model: str | None = None
    lastRun: str | None = None


class RunList(BaseModel):
    runs: list[RunInfo]
    defaultRun: str | None = Field(None, description="The run the patient dashboard shows")


class MetricRow(BaseModel):
    label: str
    higherIsBetter: bool | None = Field(None, description="None for descriptive metrics with no better direction")
    values: dict[str, float | None] = Field(description="Mean per run over the shared admissions")
    ci: dict[str, list[float] | None] = Field(default_factory=dict, description="95% bootstrap interval per run")


class PairedRow(BaseModel):
    run: str
    label: str
    better: int
    worse: int
    tied: int
    p: float = Field(description="Exact two-sided sign test against the first run")
    wilcoxonP: float | None = Field(None, description="Wilcoxon signed-rank test on the paired differences")
    difference: float | None = Field(None, description="Mean of this run minus the first run")
    differenceCi: list[float] | None = Field(None, description="95% bootstrap interval for the difference")


class RunComparison(BaseModel):
    tags: list[str]
    admissions: int = Field(description="Admissions that every run covers")
    clinicianGrade: float | None = Field(None, description="Reading grade of the clinicians' own instructions")
    metrics: list[MetricRow]
    paired: list[PairedRow]


class DrugMatch(BaseModel):
    drugbankId: str
    name: str


class SideEffectWarning(BaseModel):
    warning: str = Field(description="Plain-language sign to get help for right away")
    listedAs: list[str] = Field(description="The drug graph's terms this warning covers")


class SideEffects(BaseModel):
    getHelp: list[SideEffectWarning] = Field(description="Serious effects a patient can notice, grouped, in a fixed order")
    other: list[str] = Field(description="Every other listed effect, alphabetical")
    total: int = Field(description="0 means the graph has no side-effect list for this drug")


class MedicineInfo(BaseModel):
    listedAs: str = Field(description="The medicine as written on the discharge list")
    matches: list[DrugMatch] = Field(description="DrugBank entries it matched; a combination pill matches several")
    sideEffects: SideEffects


class TopicPart(BaseModel):
    question: str
    answer: str


class HealthTopic(BaseModel):
    id: str
    title: str
    summary: str
    parts: list[TopicPart] = Field(description="The summary split on its own questions; the first part is the overview")
    matchedOn: str = Field(description="The discharge diagnosis this topic was found from")


class VitalSign(BaseModel):
    name: str
    label: str
    value: str
    meaning: str = Field(description="What the measurement is, in plain words")


class VitalSigns(BaseModel):
    timing: str = Field(description="discharge, admission, or unstated when the note doesn't say which exam")
    measurements: list[VitalSign]
    sourceLine: str = Field(description="The note's vitals line the values came from, for checking")


class PatientHealth(BaseModel):
    encounterId: str
    available: bool = Field(description="False when the reference data files are missing")
    vitals: VitalSigns | None = Field(description="None when the note has no exam vitals that can be read")
    medicines: list[MedicineInfo]
    topics: list[HealthTopic]
    sources: list[str]


class TermLink(BaseModel):
    section: int = Field(description="Index into the encounter's sections")
    item: int = Field(description="Index into that section's items")
    start: int
    end: int
    text: str = Field(description="The words as they appear in the item")
    topicId: str
    title: str


class DrugInteraction(BaseModel):
    first: str
    second: str
    drugs: list[str] = Field(description="The DrugBank names the interaction is listed under")


class PatientInteractions(BaseModel):
    encounterId: str
    interactions: list[DrugInteraction]
    note: str



class SpecialtyOption(BaseModel):
    key: str
    label: str
