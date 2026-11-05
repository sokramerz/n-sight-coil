from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import FakeClient
from nsight.config import loadSettings
from nsight.db import Store, rowToRecord
from nsight.evaluate.metrics import (dedupe, isDegenerate, speculativeSentences, stripDosing,
                                     unsupportedNumbers)
from nsight.generate.pipeline import (buildStructured, generateDocument, protectedTerms, rewriteReasons,
                                      simplifySections, extractNarrative)
from nsight.ingest.medications import parseMedicationEntries, simplifySig
from nsight.ingest.segmentation import leaks, removeSections


# ------------------------------------------------------------- medications

def test_shorthand_translation_keeps_every_dose():
    assert simplifySig("Metoprolol Succinate XL 50 mg PO DAILY") == \
        "Metoprolol Succinate XL 50 mg by mouth once a day"
    assert simplifySig("Acetaminophen 650 mg PO Q6H:PRN pain") == \
        "Acetaminophen 650 mg by mouth every 6 hours as needed for pain"
    assert "340 mg" in simplifySig(
        "Tobramycin 40 mg/mL Solution Sig: Three Hundred Forty (340) mg Injection Q24H (every 24 hours)")


def test_medication_entries(cohort):
    meds = parseMedicationEntries(cohort[0]["dischargeMedsSection"])
    assert [m.index for m in meds] == [1, 2, 3, 4]
    assert meds[0].name == "Warfarin" and meds[0].highRisk
    assert "Disp" not in meds[0].plain and "once a day" in meds[0].plain
    assert not meds[1].highRisk


# ---------------------------------------------------------------- sections

def test_medication_sections_removed_from_model_input(cohort):
    record = rowToRecord({**{k: None for k in ("diagnoses",)}, "hadm_id": 1,
                          "model_input": cohort[0]["modelInput"],
                          "ref_instructions": cohort[0]["refInstructions"],
                          "meds_section": cohort[0]["dischargeMedsSection"],
                          "allergies_section": cohort[0]["allergiesSection"],
                          "disposition_section": "Home"})
    hidden = buildStructured(record, includeMedList=False)
    assert "Metoprolol" not in hidden and "Furosemide" not in hidden
    assert "Brief Hospital Course" in hidden and "Penicillins" in hidden
    assert "Metoprolol" in buildStructured(record, includeMedList=True)


def test_remove_sections_stops_at_real_headers_only():
    text = "A:\nx\nDischarge Medications:\n1. Drug\nDisp:*30*\n2. Other\nDischarge Disposition:\nHome"
    out = removeSections(text, ("Discharge Medications",))
    assert "Drug" not in out and "Other" not in out and "Home" in out


def test_leak_check(cohort):
    assert not leaks(cohort[0]["modelInput"], cohort[0]["refInstructions"])
    assert leaks(cohort[2]["modelInput"], cohort[2]["refInstructions"])


# ----------------------------------------------------------------- cleanup

def test_loops_detected_and_removed():
    text = "You were admitted for pneumonia. " + "Follow up with your doctor in one week.\n" * 10
    assert isDegenerate(text)
    assert dedupe(text).count("Follow up") == 1


def test_dosing_stripped_but_plain_mentions_kept():
    narrative = ("You came in with swelling.\nTake furosemide 40 mg by mouth twice a day.\n"
                 "Your furosemide helps remove extra fluid.")
    cleaned, removed = stripDosing(narrative, ["furosemide"])
    assert removed == 1
    assert "40 mg" not in cleaned and "helps remove extra fluid" in cleaned


# ---------------------------------------------------------------- pipeline

def test_sectional_document(cohort):
    client = FakeClient()
    result = generateDocument(cohort[0], client, mode="sectional")
    assert result.model == "medgemma"
    # warning signs come from the fixed list, so only three sections go to the model
    assert len(client.prompts) == 3
    assert "When to get help right away" in result.score.filledSections
    assert all("Metoprolol" not in p for p in client.prompts)
    assert [s["header"] for s in result.sections] == [
        "What happened in the hospital", "What to do over the next few days",
        "When to get help right away", "Your follow-up"]
    assert result.dosingSentencesRemoved == 1
    assert "40 mg by mouth twice a day" not in result.narrative
    assert "YOUR MEDICATIONS\n1. Warfarin" in result.document
    assert result.score.medRecall == 1.0 and result.score.highRiskMissing == 0
    assert result.score.sections == 4 and result.score.medRestatements == 0


def test_loop_counted_even_after_dedupe(cohort):
    result = generateDocument(cohort[0], FakeClient(loop=True), mode="sectional")
    assert result.score.degenerate
    assert result.narrative.count("before breakfast") == 1


def test_all_text_strips_preamble(cohort):
    result = generateDocument(cohort[0], FakeClient(), mode="allText")
    assert not result.narrative.lower().startswith("okay")


def test_unknown_mode_rejected(cohort):
    with pytest.raises(ValueError):
        generateDocument(cohort[0], FakeClient(), mode="bogus")


# --------------------------------------------------------------------- API

@pytest.fixture
def api(tmp_path, monkeypatch, cohort):
    monkeypatch.setenv("NSIGHT_DB", str(tmp_path / "test.duckdb"))
    store = Store(loadSettings().dbPath)
    store.loadCohort(cohort)
    store.close()

    from nsight.api import main
    main.app.dependency_overrides[main.getClient] = lambda: FakeClient()
    with TestClient(main.app) as client:
        yield client
    main.app.dependency_overrides.clear()


def test_health(api):
    body = api.get("/health").json()
    assert body["status"] == "ok" and body["admissionsLoaded"] == 3


def test_admission_list_hides_leaks(api):
    page = api.get("/admissions").json()
    assert page["total"] == 2
    assert {a["hadmId"] for a in page["items"]} == {20000001, 20000002}
    assert api.get("/admissions", params={"includeLeaks": True}).json()["total"] == 3
    assert api.get("/admissions", params={"search": "heart failure"}).json()["total"] == 2
    assert api.get("/admissions", params={"search": "nothing-matches"}).json()["total"] == 0


def test_admission_detail(api):
    detail = api.get("/admissions/20000001").json()
    assert detail["highRiskCount"] == 1 and len(detail["medications"]) == 4
    assert detail["medications"][3]["plain"].endswith("as needed for pain")
    assert detail["allergies"] == ["Penicillins", "Shellfish Derived"]
    assert "[redacted]" in detail["sourceNote"]
    assert api.get("/admissions/1").status_code == 404


def test_generate_then_list_and_stats(api):
    created = api.post("/admissions/20000001/documents", json={"mode": "sectional"})
    assert created.status_code == 201
    doc = created.json()
    assert len(doc["sections"]) == 4 and doc["score"]["medRecall"] == 1.0
    assert doc["includeMedList"] is False and doc["warnings"]

    docs = api.get("/admissions/20000001/documents").json()
    assert [d["id"] for d in docs] == [doc["id"]]
    assert api.get(f"/documents/{doc['id']}").json()["narrative"] == doc["narrative"]
    assert api.get("/admissions").json()["items"][0]["documentCount"] == 1

    modes = api.get("/stats").json()["modes"]
    assert modes[0]["mode"] == "sectional" and modes[0]["followedAllSections"] == 1
    assert modes[0]["restated"] == 1


def test_patients_read_from_the_store(api):
    patients = api.get("/patients").json()
    assert {p["id"] for p in patients} == {"20001001", "20001002", "20001003"}

    encounter = api.get("/patients/20001001/encounters/20000001").json()
    assert encounter["document_id"] is None and encounter["summary"] is None
    assert encounter["reason"] and len(encounter["medications"]) == 4
    assert encounter["notes"][0]["content"]

    api.post("/admissions/20000001/documents", json={"mode": "sectional"})
    encounter = api.get("/patients/20001001/encounters/20000001").json()
    assert encounter["document_id"] is not None and encounter["summary"]
    assert [s["header"] for s in encounter["sections"]] == [
        "What to do over the next few days", "When to get help right away", "Your follow-up"]
    assert all(isinstance(sec["from_record"], bool) for sec in encounter["sections"])
    assert encounter["discharge_instructions"]

    patient = api.get("/patients/20001001").json()
    assert [e["id"] for e in patient["encounters"]] == ["20000001"]
    assert api.get("/patients/20001002/encounters/20000001").status_code == 404
    assert api.get("/patients/999").status_code == 404
    assert api.get("/patients/abc").status_code == 404


def test_glossary_explains_each_term_once():
    from nsight.generate.glossary import explainSections
    sections = [{"header": "a", "text": "Get your INR checked. You had C. difficile (\"Cdiff\")."},
                {"header": "b", "text": "Repeat the INR on Monday. Avoid NSAIDs (pain medicines like ibuprofen)."}]
    out, terms = explainSections(sections)
    assert out[0]["text"] == ("Get your INR (a blood test that shows how long your blood takes to clot) checked. "
                              "You had C. difficile (\"Cdiff\") (a germ that causes serious diarrhea).")
    assert out[1]["text"] == sections[1]["text"]
    assert terms == ["INR", "C. diff"]


def test_glossary_explanations_add_no_numbers():
    from nsight.generate.glossary import TERMS
    assert not [label for label, _, explanation in TERMS if any(c.isdigit() for c in explanation)]


def test_generated_document_explains_terms(cohort):
    record = dict(cohort[0], refInstructions="Please get your INR checked in 3 days. Call your PCP with "
                  "questions. Take your medicines as listed. Weigh yourself every morning.")
    result = generateDocument(record, FakeClient(), mode="sectional")
    assert "INR (a blood test" in result.narrative and "PCP (your main doctor)" in result.narrative
    assert set(result.score.explainedTerms) >= {"INR", "PCP"}
    assert not result.score.unsupportedNumbers


def test_runs_and_comparison(api):
    assert api.get("/runs").json() == {"runs": [], "defaultRun": None}
    for hadm in (20000001, 20000002):
        api.post(f"/admissions/{hadm}/documents", json={"mode": "sectional"})
    runs = api.get("/runs").json()
    assert runs["defaultRun"] == "live" and runs["runs"][0]["admissions"] == 2

    one = api.get("/runs/compare", params={"tags": ["live"]}).json()
    assert one["admissions"] == 2 and one["paired"] == []
    numbers = next(m for m in one["metrics"] if m["label"] == "unsupported numbers")
    assert numbers["higherIsBetter"] is False and numbers["values"]["live"] is not None
    assert next(m for m in one["metrics"] if m["label"] == "narrative length")["higherIsBetter"] is None

    two = api.get("/runs/compare", params={"tags": ["live", "live"]}).json()
    assert {p["label"] for p in two["paired"]} >= {"reading grade", "unsupported numbers"}
    assert all(p["tied"] == 2 and p["p"] == 1.0 for p in two["paired"])

    assert api.get("/runs/compare", params={"tags": ["nope"]}).status_code == 404
    assert api.get("/runs/compare").status_code == 422


def test_unexplained_abbreviations():
    from nsight.evaluate.metrics import unexplainedAbbreviations
    text = "STOP furosemide. See your PCP. Get your INR (a blood test) checked. NSAIDs are out. Call the ED."
    assert unexplainedAbbreviations(text) == ["PCP", "NSAIDs", "ED"]


class WordExtractor:
    """Stands in for the NER model: any listed word is a concept."""
    vocabulary = {"furosemide", "torsemide", "potassium", "bloodwork", "swelling", "headache", "lasix"}

    def extract(self, text):
        from nsight.evaluate.concepts import normalize
        return {w for w in normalize(text).split() if w in self.vocabulary}


def test_concept_recall_and_precision():
    from nsight.evaluate.concepts import conceptScores
    doctor = "Stop furosemide. Start torsemide. Get bloodwork to check potassium."
    source = doctor + " Lasix 40 mg daily."
    summary = "Stop taking furosemide. Start torsemide. Watch for a headache (a pain in the head)."
    scores = conceptScores(WordExtractor(), doctor, source, summary, summary)
    assert scores["conceptRecall"] == 0.5      # potassium and bloodwork were dropped
    assert scores["conceptPrecision"] == round(2 / 3, 4)  # headache isn't in the record
    assert scores["doctorConcepts"] == 4.0


def test_score_run_stores_concepts_and_compare_reads_them(api):
    from nsight.db import Store
    from nsight.evaluate.compare import compareRuns
    from nsight.evaluate.concepts import scoreRun
    from nsight.api import main
    api.post("/admissions/20000001/documents", json={"mode": "sectional"})
    store: Store = main.state["store"]
    assert scoreRun(store, "live", WordExtractor()) == 1
    assert scoreRun(store, "live", WordExtractor()) == 0
    result = compareRuns(store, ["live"])
    assert "concept recall" in result.means and "unexplained abbreviations" in result.means
    body = api.get("/runs/compare", params={"tags": ["live", "live"]}).json()
    smog = next(m for m in body["metrics"] if m["label"] == "unexplained abbreviations")
    assert set(smog["ci"]) == {"live"}
    assert all(p["difference"] in (0, None) for p in body["paired"])


def test_bootstrap_and_wilcoxon():
    from nsight.evaluate.compare import bootstrapCi, wilcoxon
    low, high = bootstrapCi([1.0, 2.0, 3.0, 4.0, 5.0])
    assert 1.0 <= low < 3.0 < high <= 5.0
    assert bootstrapCi([1.0]) is None
    assert wilcoxon([0, 0]) is None
    assert wilcoxon([1.0, 2.0, 1.5, 3.0, 2.5, 1.0, 2.0, 4.0]) < 0.05


@pytest.fixture
def faqDir(tmp_path, monkeypatch):
    import json
    d = tmp_path / "faq"
    d.mkdir()
    (d / "interactions.json").write_text(json.dumps([
        {"id": "DB00682", "name": "Warfarin", "interacting_drugs": ["Acetylsalicylic acid", "Metoprolol"]},
        {"id": "DB00945", "name": "Acetylsalicylic acid", "interacting_drugs": ["Warfarin"]},
        {"id": "DB00264", "name": "Metoprolol", "interacting_drugs": []},
        {"id": "DB00695", "name": "Furosemide", "interacting_drugs": []},
        {"id": "DB00177", "name": "Valsartan", "interacting_drugs": []},
        {"id": "DB09292", "name": "Sacubitril", "interacting_drugs": []}]))
    (d / "side_effects.json").write_text(json.dumps([
        {"id": "DB00682", "name": "Warfarin", "side_effects": ["Bleeding", "Bruising"]}]))
    (d / "summaries.json").write_text(json.dumps({
        "terms": {"heart failure": "1", "congestive heart failure": "1", "atrial fibrillation": "2"},
        "topics": {"1": {"title": "Heart Failure", "summary": "Your heart does not pump well."},
                   "2": {"title": "Atrial Fibrillation", "summary": "An irregular heartbeat."}}}))
    monkeypatch.setenv("NSIGHT_FAQ_DIR", str(d))
    return d


def test_drug_matching_handles_brands_salts_and_combinations(faqDir):
    from nsight.api.healthinfo import HealthInfo
    info = HealthInfo()
    assert [d["name"] for d in info.matchDrug("Aspirin")] == ["Acetylsalicylic acid"]
    assert [d["name"] for d in info.matchDrug("Metoprolol Succinate XL")] == ["Metoprolol"]
    assert [d["name"] for d in info.matchDrug("Sacubitril-Valsartan")] == ["Sacubitril", "Valsartan"]
    assert info.matchDrug("Glucometer") == []
    meds = info.medicines(["Warfarin", "Aspirin", "Furosemide"])
    assert meds[0]["sideEffects"]["total"] == 2 and meds[2]["sideEffects"]["total"] == 0
    assert [p["second"] for p in info.interactions(["Warfarin", "Aspirin", "Furosemide"])] == ["Aspirin"]
    topics = info.topics(["Acute on chronic congestive heart failure", "Atrial fibrillation", "Gout"])
    assert [t["title"] for t in topics] == ["Heart Failure", "Atrial Fibrillation"]


def test_patient_health_endpoint(faqDir, api):
    body = api.get("/patients/20001001/health").json()
    assert body["encounterId"] == "20000001" and body["available"] is True
    assert [t["title"] for t in body["topics"]] == ["Heart Failure", "Atrial Fibrillation"]
    assert body["medicines"] and all("listedAs" in m for m in body["medicines"])
    assert body["sources"]
    assert body["vitals"]["timing"] == "discharge"
    assert [v["name"] for v in body["vitals"]["measurements"]] == [
        "temperature", "bloodPressure", "heartRate", "breathingRate", "oxygen", "weight"]
    assert "interactsWithYourMedicines" not in body["medicines"][0]
    assert api.get("/patients/999/health").status_code == 404


def test_interactions_are_a_separate_provider_route(faqDir, api):
    body = api.get("/patients/20001001/interactions").json()
    assert body["encounterId"] == "20000001" and "No severity" in body["note"]
    assert {(p["first"], p["second"]) for p in body["interactions"]} <= {("Warfarin", "Metoprolol Succinate XL"),
                                                                          ("Warfarin", "Furosemide")}


def test_term_links_point_at_the_patients_conditions():
    from nsight.api.healthinfo import HealthInfo
    info = HealthInfo()
    sections = [["Your CHF got worse, so we gave you a water pill.", "Your heart failure is better."],
                ["Call if you have pain, fever, or your Afib comes back."]]
    links = info.termLinks(sections, ["Acute on chronic systolic heart failure", "Atrial fibrillation"])
    assert [(l["section"], l["item"], l["text"]) for l in links] == [(0, 0, "CHF"), (1, 0, "Afib")]
    item = sections[1][0]
    assert item[links[1]["start"]:links[1]["end"]] == "Afib"
    assert not any(l["text"].lower() in ("pain", "fever") for l in links)


def test_topics_expand_abbreviations_and_split_on_questions():
    from nsight.api.healthinfo import HealthInfo, expandDiagnosis, questionParts
    assert expandDiagnosis("Upper GI bleed") == "Upper gastrointestinal bleeding"
    assert expandDiagnosis("HTN, Afib") == "hypertension, atrial fibrillation"
    parts = questionParts("Pneumonia", "What is pneumonia? An infection of the lungs . What causes pneumonia? Germs.")
    assert [p["question"] for p in parts] == ["What is pneumonia?", "What causes pneumonia?"]
    assert parts[0]["answer"] == "An infection of the lungs."
    assert questionParts("Cellulitis", "A skin infection.")[0]["question"] == "What is cellulitis?"
    titles = [t["title"] for t in HealthInfo().topics(["UTI", "Kidney transplant recipient"])]
    assert titles == ["Urinary Tract Infections", "Kidney Transplantation"]


def test_side_effects_rank_serious_first_and_keep_everything():
    from nsight.generate.sideeffects import rankSideEffects
    out = rankSideEffects(["Nausea", "Melena", "Anaphylactic shock", "Pruritus", "Facial edema", "Hematemesis"])
    assert [w["warning"].split(":")[0] for w in out["getHelp"]] == [
        "A severe allergic reaction", "Black or tarry stools, vomiting blood, or blood in your urine"]
    assert out["getHelp"][0]["listedAs"] == ["Anaphylactic shock", "Facial edema"]
    assert out["other"] == ["Nausea", "Pruritus"] and out["total"] == 6
    assert sum(len(w["listedAs"]) for w in out["getHelp"]) + len(out["other"]) == out["total"]


VITALS_NOTES = {
    "bare row with Epic words": ("DISCHARGE PHYSICAL EXAM:\nVITALS: 98.2 PO 126 / 72 L Lying 78 18 98 Ra\nGEN: well",
                                 "discharge", {"bloodPressure": "126/72", "oxygen": "98% on room air"}),
    "labeled with weight": ("DISCHARGE EXAM:\nVitals: T 98.1 BP 128/76 HR 74 RR 16 O2 96% RA\nWeight: 79.8 kg\nGEN: y",
                            "discharge", {"heartRate": "74 beats per minute", "weight": "79.8 kg (176 lb)"}),
    "ranges are skipped": ("PHYSICAL EXAM ON DISCHARGE:\nVS: Tmax 99.4 Tc 98.6 BP 110-134/60-72 HR 60-80 RR 16\nGen: ok",
                           "discharge", {"temperature": "98.6 °F", "breathingRate": "16 breaths per minute"}),
    "admission only": ("ON ADMISSION:\nVS: T 99.1 BP 100/60 HR 120 RR 24 SpO2 94% 4L NC\nGEN: ok",
                       "admission", {"oxygen": "94% on 4 liters of oxygen"}),
    "no exam label": ("VS: 98.4 140/82 88 18 99%RA\nGEN: ok", "unstated", {"bloodPressure": "140/82"}),
    "same line as the label": ("Discharge PE: VS: afebrile, BP 122/70, P 64, R 14, 98% RA\nGEN: ok",
                               "discharge", {"heartRate": "64 beats per minute", "oxygen": "98% on room air"}),
}


@pytest.mark.parametrize("case", VITALS_NOTES)
def test_vitals_from_the_exam(case):
    from nsight.ingest.vitals import vitalSigns
    exam, timing, expected = VITALS_NOTES[case]
    vitals = vitalSigns(f"Name: ___\nPhysical Exam:\n{exam}\n\nPertinent Results:\nx\n")
    values = {v.name: v.value for v in vitals.measurements}
    assert vitals.timing == timing
    assert all(values[k] == v for k, v in expected.items()), values
    if case == "ranges are skipped":
        assert "bloodPressure" not in values and "heartRate" not in values


def test_vitals_prefer_discharge_and_need_an_exam():
    from nsight.ingest.vitals import vitalSigns
    note = ("Physical Exam:\nADMISSION EXAM:\nVS: 101.2 90/50 120 28 88% RA\nGEN: sick\n"
            "DISCHARGE EXAM:\nVS: 98.1 118/70 80 16 97% RA\nGEN: well\n\nPertinent Results:\nx\n")
    assert vitalSigns(note).measurements[0].value == "98.1 °F"
    assert vitalSigns("Brief Hospital Course:\nVS: 98.1 118/70 80 16 97% RA\n") is None
    assert vitalSigns("Physical Exam:\nGEN: well, vitals stable\n") is None


def test_encounter_term_links_endpoint(faqDir, api):
    assert api.get("/patients/20001001/encounters/20000001/terms").status_code == 200
    assert api.get("/patients/20001001/encounters/1/terms").status_code == 404


def test_medication_changes():
    from nsight.ingest.medchanges import medicationChanges
    note = ("Brief Hospital Course:\nx\n\nMedications on Admission:\n1. Lasix 20 mg PO DAILY\n"
            "2. Warfarin 5 mg PO DAILY\n3. Lisinopril 10 mg PO DAILY\n\nDischarge Medications:\n")
    discharge = ("1. Furosemide 40 mg PO BID\n2. Warfarin 5 mg Tablet Sig: One (1) Tablet PO DAILY (Daily).\n"
                 "3. Apixaban 5 mg PO BID")
    out = medicationChanges(note, discharge)
    assert out["available"] and not out["admissionListIncomplete"]
    assert [c["name"] for c in out["new"]] == ["Apixaban"]
    assert [c["name"] for c in out["stopped"]] == ["Lisinopril"]
    assert [c["name"] for c in out["changed"]] == ["Furosemide"]  # brand name matched, dose went up
    assert out["unchanged"] == ["Warfarin"]  # same dose, different wording
    assert medicationChanges("no admission list here", discharge)["available"] is False


def test_medicine_purposes_link_to_diagnoses():
    from nsight.generate.purposes import purposeFor
    apixaban = purposeFor("Apixaban", ["New atrial fibrillation"])
    assert apixaban["purpose"].startswith("A blood thinner")
    assert "atrial fibrillation" in apixaban["forCondition"]
    assert purposeFor("Metoprolol Succinate XL", ["Gout"])["forCondition"] is None
    assert purposeFor("Sacubitril-Valsartan", [])["purpose"].startswith("Helps a weak heart")
    assert purposeFor("Glucometer", ["Diabetes"]) is None
    from nsight.generate.purposes import CLASSES, DRUG_CLASS
    assert set(DRUG_CLASS.values()) <= set(CLASSES)
    assert not [c for c, (purpose, _) in CLASSES.items() if any(ch.isdigit() for ch in purpose)]


def test_encounter_carries_purposes_and_changes(api):
    encounter = api.get("/patients/20001001/encounters/20000001").json()
    warfarin = next(m for m in encounter["medication_details"] if m["name"] == "Warfarin")
    assert warfarin["purpose"].startswith("A blood thinner") and "atrial fibrillation" in warfarin["for_condition"]
    changes = encounter["medication_changes"]
    assert changes["available"] and [c["name"] for c in changes["changed"]] == ["Furosemide"]


def test_unwrap_keeps_bullets_on_their_own_lines():
    from nsight.api.patients import unwrap
    text = "Changes:\n- STOP furosemide\n- START torsemide 40 mg once\na day.\n\nWeigh yourself\nevery morning."
    assert unwrap(text) == ("Changes:\n- STOP furosemide\n- START torsemide 40 mg once a day.\n\n"
                            "Weigh yourself every morning.")


def test_generate_validates_mode(api):
    assert api.post("/admissions/20000001/documents", json={"mode": "bogus"}).status_code == 422


# ------------------------------------------------------------ faithfulness

def test_unsupported_numbers():
    source = "Warfarin 5 mg daily. Follow up on 3/14 with cardiology."
    narrative = "Take warfarin 5 mg. See cardiology on 3/14. Your INR goal is 2.5. Call 911 if you bleed."
    assert unsupportedNumbers(narrative, source) == ["2.5"]


def test_speculation_counted():
    text = ("You had swelling in your liver. This could be due to hepatitis. "
            "Further testing may be needed. Rest at home.")
    assert speculativeSentences(text) == 2


# ---------------------------------------------------------- simplification

@pytest.fixture
def ungraded(monkeypatch):
    """The fixture text is already easy to read, so with a pronunciation dictionary installed
    every section would be skipped as simple enough. These tests are about the rewrite checks."""
    from nsight.generate import pipeline
    monkeypatch.setattr(pipeline, "readingGrade", lambda text: None)


def test_simplification_keeps_facts(cohort, ungraded):
    result = generateDocument(cohort[0], FakeClient(), mode="sectional", simplify=True)
    assert result.score.simplifiedSections >= 2 and result.score.simplifyRejected == 0
    assert "could not breathe well" in result.narrative
    assert "555-0142" in result.narrative and "Cardiology Clinic" in result.narrative
    assert not result.narrative.startswith("Sure")
    assert [s["header"] for s in result.sections][0] == "What happened in the hospital"


def test_simplification_that_drops_a_number_is_rejected(cohort, ungraded):
    result = generateDocument(cohort[0], FakeClient(dropFacts=True), mode="sectional", simplify=True)
    assert result.score.simplifyRejected >= 1
    assert "555-0142" in result.narrative
    assert any("dropped or added a fact" in w for w in result.warnings)


def test_simplification_that_invents_a_number_is_rejected(cohort, ungraded):
    result = generateDocument(cohort[0], FakeClient(inventNumbers=True), mode="sectional", simplify=True)
    assert result.score.simplifiedSections == 0 and result.score.simplifyRejected >= 2
    assert "1234" not in result.narrative and "9:00" not in result.narrative


def test_rewrite_may_spell_out_abbreviations_and_split_sentences():
    original = "- See your PCP within 1 week and take the pills PO with food because they upset the stomach."
    rewrite = ("- See your primary care doctor within 1 week.\n- Take the pills by mouth.\n"
               "- Take them with food so your stomach is not upset.")
    assert rewriteReasons(original, rewrite, {}) == []


def test_rewrite_that_piles_on_bullets_is_rejected():
    original = "- Rest at home and drink fluids."
    rewrite = "\n".join(f"- Tip number {w} for you." for w in
                         ("one", "two", "three", "four", "five", "six"))
    assert "new list items" in rewriteReasons(original, rewrite, {})


def test_one_bad_bullet_keeps_its_own_wording_only(ungraded):
    class OneBadBullet(FakeClient):
        def simplify(self, text, clean=False):
            if "scale" in text:
                return text + " Call 555-1234."
            return text.replace("approximately", "about").replace("subsequently", "then")

    section = {"header": "What to do over the next few days", "text":
               "- Weigh yourself on the bathroom scale every single morning and subsequently write it down.\n"
               "- Walk approximately ten minutes after each meal and subsequently rest in a chair."}
    out, accepted, lost, reasons = simplifySections([section], {}, OneBadBullet(), "medgemma")
    lines = out[0]["text"].splitlines()
    assert accepted == 1 and lost == 0 and reasons.get("added number", 0) == 2
    assert "subsequently write it down" in lines[0] and "555" not in out[0]["text"]
    assert lines[1].startswith("- Walk about ten minutes")


def test_doctor_bullets_stay_separate_and_whole():
    record = {"refInstructions": "We made these changes to your medicines:\n- STOP furosemide (Lasix)\n"
              "- START torsemide 40 mg once a day. This is your new water pill.\n"
              "- Weigh yourself every morning after you use the bathroom."}
    text, _ = extractNarrative(record)
    assert "- START torsemide 40 mg once a day. This is your new water pill." in text
    assert "medicines:\n- STOP furosemide (Lasix)\n" in text


def test_rewrite_that_cuts_a_condition_off_its_action_is_rejected():
    original = "- Call your team or go to the ER if you have a fever over 100.4 or chills."
    rewrite = "- Call your team or go to the ER. If you have a fever over 100.4. Or chills."
    assert "fragment" in rewriteReasons(original, rewrite, {})
    assert "fragment" not in rewriteReasons(original, "- If you have a fever over 100.4, call your team.", {})


def test_doctor_wording_is_not_counted_as_speculation():
    doctor = "We found bacteria in your blood, most likely\nfrom the catheter in your chest."
    sentence = "We found bacteria in your blood, most likely from the catheter in your chest."
    assert speculativeSentences(sentence, doctor) == 0
    assert speculativeSentences(sentence) == 1


def test_rejected_rewrites_log_reasons(cohort, ungraded):
    result = generateDocument(cohort[0], FakeClient(inventNumbers=True), mode="sectional", simplify=True)
    assert result.score.simplifyReasons.get("added number", 0) >= 2


def test_retry_with_feedback_recovers_a_dropped_fact(cohort, ungraded):
    client = FakeClient(dropFacts=True, fixOnRetry=True)
    result = generateDocument(cohort[0], client, mode="sectional", simplify=True)
    assert result.score.simplifyRejected == 0 and result.score.simplifiedSections >= 2
    retries = [p for p in client.prompts if "Your last try left out facts" in p]
    assert retries and all("TEXT:" in p for p in retries)


def test_bullet_openers_are_not_protected_names():
    text = "- Rest at home for 3 days.\n- Avoid heavy lifting.\n- See Dr. Patel at Shands."
    terms = protectedTerms(text, {})
    assert {"patel", "shands", "3"} <= terms
    assert not {"rest", "avoid", "see"} & terms


def test_simplify_ignored_for_all_text(cohort):
    client = FakeClient()
    result = generateDocument(cohort[0], client, mode="allText", simplify=True)
    assert len(client.prompts) == 1 and result.score.simplifiedSections == 0


# ------------------------------------------------------------------ compare

def test_compare_runs(tmp_path, monkeypatch, cohort, capsys):
    monkeypatch.setenv("NSIGHT_DB", str(tmp_path / "cmp.duckdb"))
    store = Store(loadSettings().dbPath)
    store.loadCohort(cohort)
    for hadm in (20000001, 20000002):
        record = rowToRecord(store.getAdmission(hadm))
        store.addDocument(hadm, generateDocument(record, FakeClient(), mode="sectional"), "base")
        store.addDocument(hadm, generateDocument(record, FakeClient(), mode="sectional",
                                                 simplify=True), "simple")
    from types import SimpleNamespace
    from nsight import cli
    cli.compare(store, SimpleNamespace(tags=["base", "simple"]))
    out = capsys.readouterr().out
    assert "2 admissions in every run" in out and "reading grade" in out and "p =" in out
    cli.compare(store, SimpleNamespace(tags=["base", "simple"], out=str(tmp_path / "cmp.csv")))
    summary = (tmp_path / "cmp.csv").read_text(encoding="utf-8")
    assert "metric,base,simple" in summary and "sign test p" in summary
    perAdmission = (tmp_path / "cmp-perAdmission.csv").read_text(encoding="utf-8").splitlines()
    assert perAdmission[0].startswith("hadm_id,run,reading grade") and len(perAdmission) == 5
    with pytest.raises(SystemExit):
        cli.compare(store, SimpleNamespace(tags=["base", "missing"]))
    cli.export(store, SimpleNamespace(tags=["base", "simple"], n=None, out=str(tmp_path / "side.csv")))
    import csv
    with (tmp_path / "side.csv").open(encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    assert rows[0][:4] == ["hadm_id", "diagnoses", "EHR source (what the model saw)", "clinician instructions"]
    assert "simple document" in rows[0] and len(rows) == 3 and "YOUR MEDICATIONS" in rows[1][5]
    cli.export(store, SimpleNamespace(tags=["base"], n=1, out=str(tmp_path / "side.xlsx")))
    assert (tmp_path / "side.xlsx").exists() or (tmp_path / "side.csv").exists()
    store.close()


# ------------------------------------------------------------------- review

def test_review_page(tmp_path, monkeypatch, cohort):
    monkeypatch.setenv("NSIGHT_DB", str(tmp_path / "rev.duckdb"))
    store = Store(loadSettings().dbPath)
    store.loadCohort(cohort)
    for hadm in (20000001, 20000002):
        record = rowToRecord(store.getAdmission(hadm))
        store.addDocument(hadm, generateDocument(record, FakeClient(), mode="sectional"), "base")
        store.addDocument(hadm, generateDocument(record, FakeClient(inventNumbers=True), mode="sectional",
                                                 simplify=True), "simple")
    from types import SimpleNamespace
    from nsight import cli
    cli.review(store, SimpleNamespace(tags=["base", "simple"], n=None, out=None, no_open=True))
    page = (tmp_path / "review-base-simple.html").read_text(encoding="utf-8")
    assert page.count('<section class="adm"') == 2 and "Clinician (reference)" in page
    assert "<script>alert" not in page
    store.close()


def test_highlight_escapes_and_marks():
    from nsight.review import highlight
    out = highlight("Call <b>555</b> if fever over 101.5, possibly an infection.", ["101.5", "555"])
    assert "&lt;b&gt;" in out and '<mark class="num">101.5</mark>' in out
    assert '<mark class="num">555</mark>' in out and '<mark class="spec">possibly</mark>' in out


# ------------------------------------------------- doctor's instructions as input

REF = """Dear Mr. ___,

It was a pleasure taking care of you at the ___.
You had an infection in your blood. Continue IV antibiotics for 14 days.
Get an MRI of your kidneys. Have bloodwork drawn by your visiting nurse.
Follow up with Dr. Patel in Transplant clinic.

We wish you all the best,
Your ___ Team"""


def test_doctor_instructions_reach_the_prompt(cohort):
    record = {**cohort[0], "refInstructions": REF}
    client = FakeClient()
    generateDocument(record, client, mode="sectional")
    sectionPrompts = [p for p in client.prompts if "Section:" in p]
    assert all("WHAT THE DOCTOR WROTE FOR THE PATIENT" in p and "MRI of your kidneys" in p
               for p in sectionPrompts)
    assert not any("pleasure taking care" in p or "wish you all the best" in p for p in sectionPrompts)

    chartOnly = FakeClient()
    result = generateDocument(record, chartOnly, mode="sectional", useInstructions=False)
    assert not any("MRI of your kidneys" in p for p in chartOnly.prompts)
    assert result.score.fromInstructions is False


def test_instruction_coverage_counts_missed_items(cohort):
    from nsight.evaluate.metrics import instructionCoverage
    record = {**cohort[0], "refInstructions": REF}
    items, missed = instructionCoverage(record, "What to do over the next few days:\n"
                                                "Keep taking your antibiotics for 14 days. "
                                                "A nurse will draw blood work at home.")
    assert {"MRI", "patel", "transplant", "follow-up appointment"} <= set(missed)
    assert "antibiotics" not in missed and "14" not in missed and "bloodwork" not in missed
    assert "team" not in missed and items >= 7
    # the section heading alone does not count as covering the follow-up
    _, missed = instructionCoverage(record, "Your follow-up:\nNothing here.")
    assert "follow-up appointment" in missed


def test_generated_document_reports_coverage(cohort):
    record = {**cohort[0], "refInstructions": REF}
    result = generateDocument(record, FakeClient(), mode="sectional", generative=True)
    assert result.score.strategy == "generate" and result.score.instructionItems > 0
    assert result.score.instructionCoverage is not None and result.score.instructionCoverage < 1
    assert any("doctor's instructions" in w for w in result.warnings)


def test_extract_sorts_the_doctors_sentences(cohort):
    from nsight.synthetic import syntheticRows
    row = syntheticRows()[1]
    record = {**cohort[0], **{k: row[k] for k in ("refInstructions", "modelInput", "dischargeMedsSection")}}
    client = FakeClient()
    result = generateDocument(record, client, mode="sectional")
    assert result.score.strategy == "extract" and result.score.instructionCoverage == 1.0
    assert not any("Section:" in p for p in client.prompts)
    sections = {s["header"]: s["text"] for s in result.sections}
    # the doctor's own dosing line stays, and appointments come from the note too
    assert "START torsemide 40 mg once a day" in sections["What to do over the next few days"]
    assert "3 pounds in a day" in sections["When to get help right away"]
    assert "Heart Failure Clinic" in sections["Your follow-up"]
    assert "Sincerely" not in result.narrative and "Dear" not in result.narrative


def test_sparse_instructions_fall_back_to_writing(cohort):
    from nsight.synthetic import syntheticRows
    row = syntheticRows()[5]
    record = {**cohort[0], **{k: row[k] for k in ("refInstructions", "modelInput", "dischargeMedsSection")}}
    result = generateDocument(record, FakeClient(), mode="sectional")
    assert result.score.strategy == "generate"


def test_cap_bullets_stops_runaway_lists():
    from nsight.generate.pipeline import capBullets
    text = "When to get help right away:\n" + "\n".join(f"* You may experience thing {i}." for i in range(30))
    assert capBullets(text).count("You may experience") == 2
    names = ["cardiology", "nephrology", "surgery", "radiology", "pulmonary", "endocrine", "neurology",
             "dermatology", "urology", "oncology", "hepatology", "rheumatology"]
    text = "Your follow-up:\n" + "\n".join(f"* See {n} clinic soon." for n in names) + "\n* You may"
    assert capBullets(text).count("\n*") == 8


def test_orders_are_split_from_medications():
    entries = parseMedicationEntries(
        "1. Furosemide 20 mg PO DAILY\n"
        "2. Outpatient Lab Work Bloodwork: CBC, Tacrolimus trough ICD-9: V42.0 Contact: Dr ___ Fax: ___\n"
        "3. Aspirin 81 mg PO DAILY")
    meds = [e for e in entries if e.kind == "med"]
    orders = [e for e in entries if e.kind == "order"]
    assert [m.index for m in meds] == [1, 2]
    assert orders[0].plain == "Lab Work Bloodwork: CBC, Tacrolimus trough"


def test_pharmacy_fields_and_ranges():
    assert simplifySig("CefePIME 2 g IV Q12H RX *cefepime [Maxipime] 2 gram 1 gm IV q12hr "
                       "Disp #*17 Vial Refills:*0") == "CefePIME 2 g into a vein every 12 hours"
    assert "every 4 to 6 hours as needed for pain" in simplifySig("Oxycodone 5 mg PO Q4-6HRS PRN pain")


def test_rewrite_that_drops_a_test_is_rejected(cohort):
    from nsight.generate.pipeline import checkRewrite
    original = "You need an MRI of your kidneys. A nurse will do your bloodwork."
    assert checkRewrite(original, "A nurse will take some blood.", cohort[0]) == "lostFact"
    assert checkRewrite(original, "Get an MRI. A nurse will take blood work at home.", cohort[0]) != "lostFact"


def test_synthetic_cases_load_and_generate(tmp_path, monkeypatch):
    from nsight.synthetic import syntheticRows
    monkeypatch.setenv("NSIGHT_DB", str(tmp_path / "syn.duckdb"))
    store = Store(loadSettings().dbPath)
    assert store.loadCohort(syntheticRows()) == {"loaded": 6, "leaked": 0}
    for row in syntheticRows():
        record = rowToRecord(store.getAdmission(int(row["hadm_id"])))
        result = generateDocument(record, FakeClient(), mode="sectional")
        assert result.score.sections == 4
    store.close()


def test_titles_do_not_end_sentences():
    from nsight.evaluate.metrics import dedupe
    text = "Schedule a visit with Dr. Lee in 2 weeks.\nYou should also see Dr. Lee in 2 weeks for a checkup."
    assert "Dr. Lee in 2 weeks for a checkup" in dedupe(text)


def test_short_durations_are_coverage_items(cohort):
    from nsight.evaluate.metrics import instructionCoverage
    record = {**cohort[0], "refInstructions": "Take pantoprazole twice a day for 8 weeks."}
    _, missed = instructionCoverage(record, "Keep taking pantoprazole for eight weeks.")
    assert "8 week" not in missed
    _, missed = instructionCoverage(record, "Keep taking pantoprazole.")
    assert "8 week" in missed


def test_med_list_labels_and_splits():
    entries = parseMedicationEntries("1. Glargine 22 Units Bedtime\nHumalog 1 Unit per 10 grams carbohydrate\n"
                                     "2. Apixaban 5 mg PO BID\n3. Cephalexin 500 mg PO Q6H Duration: 3 Days")
    plain = [e.plain for e in entries]
    assert plain[0] == "Glargine 22 Units at bedtime" and plain[1].startswith("Humalog")
    assert plain[2].endswith("(blood thinner)") and plain[3].endswith("for 3 days")
    assert [e.index for e in entries] == [1, 2, 3, 4]


def test_intro_line_passes_its_section_to_bullets():
    from nsight.generate.extract import sortInstructions
    text = ("You were admitted for chest pain. We ruled out a heart attack.\n\n"
            "Please call your doctor or return to the emergency department for any of the following:\n"
            "* You experience new chest pain, pressure, squeezing or tightness.\n"
            "* You have shortness of breath.\n\n"
            "Activity:\n- No heavy lifting for 2 weeks.\n- Walk every day.")
    sections = sortInstructions(text)
    assert len(sections["When to get help right away"]) == 3
    assert "Walk every day." in sections["What to do over the next few days"]


def test_extract_fills_empty_sections_without_the_model(cohort):
    record = {**cohort[0], "refInstructions": "You were admitted for heart failure. We gave you IV "
              "diuretics. Your breathing got better and you feel well now.",
              "dischargeDiagnoses": ["Acute on chronic heart failure", "Atrial fibrillation"]}
    client = FakeClient()
    result = generateDocument(record, client, mode="sectional")
    assert result.score.strategy == "extract" and not client.prompts
    sections = {s["header"]: s["text"] for s in result.sections}
    help_ = sections["When to get help right away"]
    assert "weight goes up quickly" in help_ and "heart races" in help_
    assert "Bleeding that will not stop" in help_      # warfarin is on the list
    assert help_.strip().endswith("call 911.")
    assert "When to get help right away" in result.score.filledSections
    assert any("standard warning signs" in w for w in result.warnings)
    assert not result.score.unsupportedNumbers and not result.score.conflicts


def test_warning_signs_are_capped_and_fall_back():
    from nsight.generate.redflags import warningSigns
    many = warningSigns(["sepsis", "pneumonia", "heart failure", "cirrhosis", "GI bleed"], None)
    assert len(many) == 6 and many[-1].startswith("Chest pain")
    assert warningSigns(["broken wrist"], None) == ["Chest pain, trouble breathing, or fainting: call 911."]


def test_rewrite_that_adds_speculation_is_rejected(cohort):
    from nsight.generate.pipeline import checkRewrite
    original = "Your kidneys were not working well. We gave you fluids."
    assert checkRewrite(original, "Your kidneys were weak, possibly from dehydration. We gave you fluids.",
                        cohort[0]) == "lostFact"


def test_rewrite_that_balloons_or_invents_is_rejected(cohort):
    from nsight.generate.pipeline import checkRewrite
    original = "You had an infection in your leg. We treated it with antibiotics."
    ballooned = original + "\n" + "\n".join(f"* If you have problem {i}, call us right away." for i in range(20))
    assert checkRewrite(original, ballooned, cohort[0]) == "lostFact"
    assert checkRewrite(original, "Your leg was infected. Follow up with Dr. Smith on July 27th. "
                        "We gave you antibiotics.", cohort[0]) == "lostFact"
    assert checkRewrite(original, "Your leg was infected and your tummy hurt. We gave you antibiotics.",
                        cohort[0]) == "lostFact"


def test_template_filler_is_dropped():
    from nsight.generate.extract import sortInstructions
    sections = sortInstructions("You were treated for pneumonia.\n\nPlease see details below.\n"
                                "Take all of your antibiotics.")
    assert sections["What to do over the next few days"] == ["Take all of your antibiotics."]


def test_fixed_sections_are_not_rewritten(cohort):
    record = {**cohort[0], "refInstructions": "You were admitted for heart failure. We gave you IV "
              "diuretics that removed a lot of extra fluid from your body over several days. Your "
              "breathing improved considerably and you are now feeling much better overall."}
    client = FakeClient()
    result = generateDocument(record, client, mode="sectional", simplify=True)
    rewritten = [p for p in client.prompts if p.startswith("Rewrite this part")]
    assert not any("call 911" in p or "Take your medicines exactly" in p for p in rewritten)


def test_kidney_cases_match_on_diagnoses_medicines_and_history():
    from nsight.api.specialties import SPECIALTIES, caseReasons
    kidney = SPECIALTIES["nephrology"]
    assert caseReasons(kidney, ["AKI on CKD", "Pneumonia"], [], None) == ["AKI on CKD"]
    assert caseReasons(kidney, ["Adrenal insufficiency"], [], None) == []
    assert caseReasons(kidney, ["Cellulitis"], ["Sevelamer Carbonate", "Cephalexin"], None) == ["Takes Sevelamer Carbonate"]
    note = "Past Medical History:\nESRD on hemodialysis MWF\nHTN\n\nSocial History:\nlives alone\n"
    assert caseReasons(kidney, ["Hip fracture"], [], note) == ["History: ESRD"]
    # only the past history counts, not a passing mention elsewhere in the note
    assert caseReasons(kidney, ["Sepsis"], [], "Brief Hospital Course:\nNo need for hemodialysis.\n") == []


def test_patient_search_by_id_words_and_specialty(api):
    assert [p["id"] for p in api.get("/patients", params={"search": "20001001"}).json()] == ["20001001"]
    assert len(api.get("/patients", params={"search": "2000"}).json()) == 3
    assert len(api.get("/patients", params={"search": "heart failure"}).json()) == 3
    assert api.get("/patients", params={"search": "gout"}).json() == []
    assert api.get("/patients", params={"specialty": "nephrology"}).json() == []
    assert api.get("/patients", params={"specialty": "dermatology"}).status_code == 422
    assert api.get("/specialties").json() == [{"key": "nephrology", "label": "Kidney (nephrology)"}]
    assert all(p["matches"] == [] for p in api.get("/patients").json())


def test_fictional_kidney_cases(tmp_path):
    from nsight.api.patients import StorePatientRepository
    from nsight.synthetic import syntheticRows
    store = Store(tmp_path / "synthetic.duckdb")
    store.loadCohort(syntheticRows())
    found = StorePatientRepository(store).list_patients(specialty="nephrology")
    reasons = {p.matches[0].encounter_id: p.matches[0].reasons for p in found}
    assert set(reasons) == {"90000001", "90000002"}
    assert "Chronic kidney disease stage 3" in reasons["90000002"]
    store.close()


def test_word_search_flags_the_matching_diagnosis(api):
    found = api.get("/patients", params={"search": "atrial"}).json()
    assert found and found[0]["matches"][0]["reasons"] == ["Atrial fibrillation"]


def test_rich_items_take_explanations_out_of_the_text():
    from nsight.api.richtext import richSections
    from nsight.generate.glossary import explainSections
    sections, _ = explainSections([
        {"header": "a", "text": "- You will need IV antibiotics through the PICC line until [redacted].\n- Get a CBC."},
        {"header": "b", "text": "- Call radiology at [redacted] for your MRI.\n- See Dr. [redacted], [redacted] at 10:30 AM.\n"
                                "- Ask about IV fluids."}])
    items = [[line[2:] for line in s["text"].splitlines()] for s in sections]
    assert "(through a vein)" in items[0][0]
    rich = richSections(items)
    first = rich[0][0]
    assert first["text"] == "You will need IV antibiotics through the PICC line until [redacted]."
    assert [(s["kind"], first["text"][s["start"]:s["end"]]) for s in first["spans"]] == [
        ("term", "IV"), ("term", "PICC line"), ("removed", "[redacted]")]
    assert first["spans"][2]["label"] == "date"
    assert [s["label"] for s in rich[1][0]["spans"] if s["kind"] == "removed"] == ["phone number"]
    assert [s["label"] for s in rich[1][1]["spans"]] == ["name", "date"]
    # each term is explained once per document
    assert rich[1][2]["spans"] == [] and rich[1][2]["text"] == "Ask about IV fluids."


def test_rich_offsets_count_like_javascript():
    from nsight.api.richtext import richSections
    rich = richSections([["Temp 100.4 °F 🌡 then your CBC."]])[0][0]
    span = rich["spans"][0]
    assert span["kind"] == "term"
    assert rich["text"].encode("utf-16-le")[span["start"] * 2:span["end"] * 2].decode("utf-16-le") == "CBC"


def test_condition_span_keeps_the_term_explanation():
    from nsight.api.richtext import richSections
    link = {"section": 0, "item": 0, "start": 5, "end": 8, "topicId": "199", "title": "Heart Failure"}
    rich = richSections([["Your CHF is better."]], lambda clean: [link])[0][0]
    assert len(rich["spans"]) == 1 and rich["spans"][0]["kind"] == "condition"
    assert rich["spans"][0]["topicId"] == "199"
    assert rich["spans"][0]["explanation"].startswith("congestive heart failure")


def test_tall_man_names_and_plain_reason():
    from nsight.api.patients import plainReason
    from nsight.ingest.drugnames import plainCase
    assert plainCase("CefePIME 2 g, predniSONE, hydrALAZINE, LORazepam") == "Cefepime 2 g, prednisone, hydralazine, Lorazepam"
    assert plainCase("HCTZ, NSAIDs, MyChart, Metoprolol Succinate XL") == "HCTZ, NSAIDs, MyChart, Metoprolol Succinate XL"
    assert plainReason("Pseudomonas bacteremia") == "Infection in the blood (Pseudomonas bacteremia)"
    assert plainReason("New atrial fibrillation") == "Irregular heartbeat (atrial fibrillation)"
    assert plainReason("Hip fracture") is None
    assert plainReason("Hip fracture", "Hip Injuries") == "Hip Injuries (Hip fracture)"


def test_two_glossary_styles():
    from nsight.api.richtext import explanationSentence, richSections, styledItem
    original = ("You will need IV (through a vein) antibiotics through the PICC line (a thin tube in a vein, "
                "used to give medicine) until [redacted].")
    rich = richSections([[original]])[0][0]
    assert styledItem(original, rich, "inline") == original.replace("[redacted]", "[date on your paperwork]")
    assert styledItem(original, rich, "separate").split("\n") == [
        "You will need IV antibiotics through the PICC line until [date on your paperwork].",
        "IV means through a vein.",
        "A PICC line is a thin tube in a vein, used to give medicine."]
    assert explanationSentence("NSAIDs", "pain medicines like ibuprofen and naproxen") == \
        "NSAIDs are pain medicines like ibuprofen and naproxen."
    assert explanationSentence("C. diff", "a germ that causes serious diarrhea") == "C. diff is a germ that causes serious diarrhea."
    assert explanationSentence("edema", "swelling") == "Edema means swelling."


def test_encounter_glossary_style_parameter(tmp_path):
    import json as jsonlib
    from nsight.api.patients import StorePatientRepository
    from nsight.synthetic import syntheticRows
    store = Store(tmp_path / "glossary.duckdb")
    store.loadCohort(syntheticRows())
    sections = [{"header": "What to do over the next few days",
                 "text": "- Get a CBC (a blood test that counts your blood cells) on [redacted]."}]
    store.con.execute("INSERT INTO documents (hadm_id, mode, model, source, sections, score) "
                      "VALUES (90000001, 'sectional', 'm', 't', ?, '{}')", [jsonlib.dumps(sections)])
    repo = StorePatientRepository(store)
    separate = repo.get_encounter("90000002", "90000001")
    assert separate.glossary_style == "separate"
    assert separate.sections[0].items == ["Get a CBC on [date on your paperwork].\nCBC is a blood test that counts your blood cells."]
    inline = repo.get_encounter("90000002", "90000001", "inline")
    assert inline.sections[0].items == ["Get a CBC (a blood test that counts your blood cells) on [date on your paperwork]."]
    assert inline.sections[0].rich_items == separate.sections[0].rich_items
    store.close()
