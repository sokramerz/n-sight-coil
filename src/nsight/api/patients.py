import json
import os
import re
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from nsight.api.richtext import GLOSSARY_STYLES, richSections, styledItem
from nsight.api.specialties import SPECIALTIES, caseReasons
from nsight.db import Store, toList
from nsight.generate.prompts import SECTION_HEADERS
from nsight.generate.purposes import CONDITIONS, purposeFor
from nsight.ingest.medchanges import medicationChanges
from nsight.ingest.cleaning import stripPlaceholders
from nsight.ingest.drugnames import plainCase
from nsight.ingest.medications import allergyLines, parseMedicationEntries

HAPPENED = SECTION_HEADERS[0]
BULLET = ("- ", "* ", "\u2022 ")


class Note(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    content: str


class TextSpan(BaseModel):
    start: int = Field(description="UTF-16 offset, as JavaScript indexes strings")
    end: int
    kind: str = Field(description="term, removed, or condition")
    explanation: str | None = Field(None, description="term (and a condition that is also a term): plain meaning")
    label: str | None = Field(None, description="removed: name, date, phone number, or detail")
    topicId: str | None = Field(None, description="condition: MedlinePlus topic for the pop-up")
    title: str | None = None


class RichItem(BaseModel):
    text: str = Field(description="Plain text, never markup")
    spans: list[TextSpan] = []


class InstructionSection(BaseModel):
    header: str
    items: list[str]
    from_record: bool = False
    rich_items: list[RichItem] = Field([], description="The items without the explanations written in, plus spans")


class MedicationDetail(BaseModel):
    text: str
    name: str
    purpose: str | None = None
    for_condition: str | None = None


class MedicationChange(BaseModel):
    name: str
    before: str | None = None
    now: str | None = None


class MedicationChanges(BaseModel):
    available: bool
    admission_list_incomplete: bool = False
    new: list[MedicationChange] = []
    stopped: list[MedicationChange] = []
    changed: list[MedicationChange] = []
    unchanged: list[str] = []


class Encounter(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    admission_date: datetime | None = None
    discharge_date: datetime | None = None
    service: str | None = None
    reason: str | None = None
    reason_plain: str | None = Field(None, description="The first diagnosis in plain words, with the diagnosis after it")
    provider: str | None = None
    location: str | None = None
    original_summary: str | None = None
    summary: str | None = None
    rich_summary: RichItem | None = None
    glossary_style: str = Field("separate", description="separate: explanations on their own line after the item; "
                                                        "inline: in parentheses after the word")
    discharge_instructions: list[str]
    notes: list[Note]
    sections: list[InstructionSection] = []
    medications: list[str] = []
    allergies: list[str] = []
    document_id: int | None = None
    model: str | None = None
    medication_details: list[MedicationDetail] = []
    medication_changes: MedicationChanges | None = None


class Patient(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    date_of_birth: str | None = None
    sex: str | None = None
    encounters: list[Encounter]


class CaseMatch(BaseModel):
    encounter_id: str
    reasons: list[str] = Field(description="Why this encounter matched: diagnoses, medicines, or past history")


class PatientSummary(BaseModel):
    id: str
    name: str
    date_of_birth: str | None = None
    sex: str | None = None
    latest_encounter: Encounter | None = None
    matches: list[CaseMatch] = []


class PatientRepository(Protocol):
    def list_patients(self, search: str | None = None, specialty: str | None = None) -> list[PatientSummary]: ...

    def get_patient(self, patient_id: str) -> Patient | None: ...

    def get_encounter(self, patient_id: str, encounter_id: str) -> Encounter | None: ...


class TestPatientRepository:
    def __init__(self, patients: list[Patient]) -> None:
        for patient in patients:
            patient.encounters.sort(key=lambda encounter: encounter.admission_date or datetime.min, reverse=True)
        self._patients = {patient.id: patient for patient in patients}

    def list_patients(self, search: str | None = None, specialty: str | None = None) -> list[PatientSummary]:
        # the sample data has no diagnoses, so only the ID search applies here
        return [
            PatientSummary(
                id=patient.id,
                name=patient.name,
                date_of_birth=patient.date_of_birth,
                sex=patient.sex,
                latest_encounter=patient.encounters[0] if patient.encounters else None,
            )
            for patient in self._patients.values() if not search or patient.id.startswith(search.strip())
        ]

    def get_patient(self, patient_id: str) -> Patient | None:
        return self._patients.get(patient_id)

    def get_encounter(self, patient_id: str, encounter_id: str) -> Encounter | None:
        patient = self.get_patient(patient_id)
        if patient is None:
            return None
        return next((encounter for encounter in patient.encounters if encounter.id == encounter_id), None)


def build_sample_repository() -> TestPatientRepository:
    """A made-up patient for running the API without a store. Not from MIMIC."""
    encounter = Encounter(
        id="90000101",
        admission_date=datetime.fromisoformat("2180-03-02T09:15:00"),
        discharge_date=datetime.fromisoformat("2180-03-06T13:30:00"),
        service="MED",
        reason="Community acquired pneumonia",
        summary="Hospital admission for cough, fever, and shortness of breath.",
        original_summary=(
            "You were admitted with a cough, fever, and trouble breathing. A chest X-ray showed "
            "pneumonia, which was treated with antibiotics. Your breathing improved and you were "
            "able to go home."
        ),
        discharge_instructions=[
            "Finish all of your antibiotic pills, even if you feel better.",
            "Take medications as prescribed.",
            "Contact your care team if your fever comes back or your breathing gets worse.",
        ],
        notes=[
            Note(
                id="90000100-DS-1",
                title="Discharge summary",
                content=(
                    "Chief complaint: cough, fever. "
                    "Made-up patient with a history of asthma, admitted for community acquired "
                    "pneumonia and treated with oral antibiotics."
                ),
            ),
            Note(
                id="90000100-DS-2",
                title="Progress note",
                content="Afebrile for 48 hours. Breathing comfortably on room air.",
            ),
        ],
    )
    patient = Patient(
        id="90000100",
        name="Sample Patient",
        date_of_birth=None,
        sex="M",
        encounters=[encounter],
    )
    return TestPatientRepository([patient])


def parseTime(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


def unwrap(text: str | None) -> str | None:
    """Join the note's hard-wrapped lines back into paragraphs."""
    if not text:
        return None
    paragraphs = []
    for block in text.split("\n\n"):
        lines: list[str] = []
        for line in (l.strip() for l in block.splitlines()):
            if not line:
                continue
            # a bullet starts its own line; anything else continues the line above
            if lines and not line.startswith(BULLET):
                lines[-1] += " " + line
            else:
                lines.append(line)
        if lines:
            paragraphs.append("\n".join(lines))
    return "\n\n".join(paragraphs) or None


def sectionItems(text: str) -> list[str]:
    items = []
    for line in (text or "").splitlines():
        line = line.strip()
        for marker in BULLET:
            line = line.removeprefix(marker)
        if line:
            items.append(line)
    return items


def plainChange(change: dict) -> MedicationChange:
    return MedicationChange(**{k: plainCase(v) for k, v in change.items()})


def plainReason(diagnosis: str | None, topicTitle: str | None = None) -> str | None:
    """'Pseudomonas bacteremia' -> 'Infection in the blood (Pseudomonas bacteremia)'."""
    if not diagnosis:
        return None
    label = next((label for label, pattern in CONDITIONS.values() if re.search(pattern, diagnosis.lower())), None)
    label = re.sub(r"^(?:a|an) ", "", label) if label else topicTitle
    if not label:
        return None
    label = label[0].upper() + label[1:]
    return label if "(" in label or label.lower() == diagnosis.lower() else f"{label} ({diagnosis})"


class StorePatientRepository:
    """Patients and encounters read from the DuckDB store the pipeline writes to.

    A patient is a MIMIC subject and an encounter is one admission. The accessible
    summary is the latest generated document for that admission, preferring the run
    tagged NSIGHT_DOC_SOURCE when it is set.
    """

    def __init__(self, store: Store, documentSource: str | None = None, healthInfo=None,
                 glossaryStyle: str | None = None) -> None:
        self.store = store
        self.healthInfo = healthInfo
        style = glossaryStyle or os.environ.get("NSIGHT_GLOSSARY_STYLE", "separate")
        self.glossaryStyle = style if style in GLOSSARY_STYLES else "separate"
        self.documentSource = documentSource if documentSource is not None else os.environ.get("NSIGHT_DOC_SOURCE", "")

    def latestDocument(self, hadmId: int) -> dict | None:
        rows = self.store.query(
            "SELECT id, model, sections, score FROM documents WHERE hadm_id = ? AND mode = 'sectional' "
            "ORDER BY (source = ?) DESC, id DESC LIMIT 1", [hadmId, self.documentSource])
        return rows[0] if rows else None

    def toEncounter(self, row: dict, glossaryStyle: str | None = None) -> Encounter:
        style = glossaryStyle or self.glossaryStyle
        diagnoses = toList(row.get("diagnoses"))
        entries = [m for m in parseMedicationEntries(row.get("meds_section")) if m.kind == "med"]
        details = []
        for m in entries:
            purpose = purposeFor(m.name, diagnoses) or {}
            details.append(MedicationDetail(text=plainCase(m.plain), name=plainCase(m.name),
                                            purpose=purpose.get("purpose"), for_condition=purpose.get("forCondition")))
        changes = medicationChanges(row.get("model_input"), row.get("meds_section"))
        doc = self.latestDocument(row["hadm_id"])
        sections = []
        summary = None
        if doc:
            # sections the doctor left empty and the pipeline filled from the record
            filled = set(json.loads(doc["score"] or "{}").get("filledSections") or [])
            for section in json.loads(doc["sections"] or "[]"):
                header = section.get("header")
                items = [plainCase(i) for i in sectionItems(section.get("text", ""))]
                if header == HAPPENED:
                    summary = " ".join(items)
                elif header:
                    sections.append(InstructionSection(header=header, items=items, from_record=header in filled))
        info = self.healthInfo
        # the summary reads first, so it comes first: each term is explained where it first appears
        rich = richSections([[summary] if summary else []] + [s.items for s in sections],
                            (lambda clean: info.termLinks(clean, diagnoses)) if info is not None else None)
        for section, items in zip(sections, rich[1:]):
            section.rich_items = [RichItem(**i) for i in items]
            section.items = [styledItem(original, r, style) for original, r in zip(section.items, items)]
        if summary:
            summary = styledItem(summary, rich[0][0], style)
        topics = self.healthInfo.topics(diagnoses[:1]) if self.healthInfo is not None and diagnoses else []
        return Encounter(
            id=str(row["hadm_id"]),
            admission_date=parseTime(row.get("admit_time")),
            discharge_date=parseTime(row.get("disch_time")),
            service=row.get("service"),
            reason=diagnoses[0] if diagnoses else None,
            reason_plain=plainReason(diagnoses[0] if diagnoses else None, topics[0]["title"] if topics else None),
            original_summary=unwrap(stripPlaceholders(row.get("ref_instructions"))),
            summary=summary,
            rich_summary=RichItem(**rich[0][0]) if summary else None,
            glossary_style=style,
            discharge_instructions=[item for s in sections for item in s.items],
            notes=[Note(id=row.get("note_id") or str(row["hadm_id"]), title="Discharge summary",
                        content=stripPlaceholders(row.get("model_input")) or "")],
            sections=sections,
            medications=[plainCase(m.plain) for m in parseMedicationEntries(row.get("meds_section"))],
            allergies=allergyLines(row.get("allergies_section")),
            document_id=doc["id"] if doc else None,
            model=doc["model"] if doc else None,
            medication_details=details,
            medication_changes=MedicationChanges(
                available=changes["available"], admission_list_incomplete=changes["admissionListIncomplete"],
                new=[plainChange(c) for c in changes["new"]],
                stopped=[plainChange(c) for c in changes["stopped"]],
                changed=[plainChange(c) for c in changes["changed"]],
                unchanged=[plainCase(n) for n in changes["unchanged"]]),
        )

    def admissionRows(self, subjectId: int | None = None) -> list[dict]:
        where, params = ("WHERE subject_id = ?", [subjectId]) if subjectId is not None else ("", [])
        return self.store.query(
            "SELECT hadm_id, subject_id, note_id, service, admit_time, disch_time, model_input, "
            f"ref_instructions, meds_section, allergies_section, diagnoses FROM admissions {where} "
            "ORDER BY admit_time DESC", params)

    def list_patients(self, search: str | None = None, specialty: str | None = None) -> list[PatientSummary]:
        """Every patient, or those with an encounter matching the search and the specialty.

        A number searches patient and encounter IDs by prefix; words search the diagnoses.
        """
        rule = SPECIALTIES.get(specialty) if specialty else None
        search = (search or "").strip()
        byPatient: dict[int, list[dict]] = {}
        for row in self.admissionRows():
            byPatient.setdefault(row["subject_id"], []).append(row)
        out = []
        for subjectId, rows in byPatient.items():
            matches = []
            for row in rows:
                diagnoses = toList(row.get("diagnoses"))
                if search.isdigit():
                    if not (str(subjectId).startswith(search) or str(row["hadm_id"]).startswith(search)):
                        continue
                reasons = []
                if search and not search.isdigit():
                    reasons = [d for d in diagnoses if search.lower() in d.lower()]
                    if not reasons:
                        continue
                if rule:
                    medicines = [m.name for m in parseMedicationEntries(row.get("meds_section")) if m.kind == "med"]
                    specialtyReasons = caseReasons(rule, diagnoses, medicines, row.get("model_input"))
                    if not specialtyReasons:
                        continue
                    reasons += [r for r in specialtyReasons if r not in reasons]
                matches.append(CaseMatch(encounter_id=str(row["hadm_id"]), reasons=reasons))
            if (search or rule) and not matches:
                continue
            out.append(PatientSummary(id=str(subjectId), name=f"Patient {subjectId}",
                                      latest_encounter=self.toEncounter(rows[0]),
                                      matches=matches if (search or rule) else []))
        return out

    def get_patient(self, patient_id: str) -> Patient | None:
        if not patient_id.isdigit():
            return None
        rows = self.admissionRows(int(patient_id))
        if not rows:
            return None
        return Patient(id=patient_id, name=f"Patient {patient_id}",
                       encounters=[self.toEncounter(r) for r in rows])

    def get_encounter(self, patient_id: str, encounter_id: str, glossaryStyle: str | None = None) -> Encounter | None:
        if not (patient_id.isdigit() and encounter_id.isdigit()):
            return None
        row = self.store.getAdmission(int(encounter_id))
        if row is None or row["subject_id"] != int(patient_id):
            return None
        return self.toEncounter(row, glossaryStyle)

