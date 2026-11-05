"""Synthetic admissions shaped like cohortV2.json rows. No real patient data."""
from __future__ import annotations

import re

import pytest

from nsight.config import Settings
from nsight.generate.model_client import Completion, OllamaClient

NOTE = """Name: ___ Unit No: ___
Allergies:
Penicillins / Shellfish Derived

Chief Complaint:
Shortness of breath

History of Present Illness:
Ms. ___ is a ___ year old woman with atrial fibrillation and heart failure who came in with
three days of worsening shortness of breath and leg swelling.

Physical Exam:
ADMISSION PHYSICAL EXAM:
VS: 98.0 152/90 104 24 91% 2L NC
GEN: Mild distress

DISCHARGE PHYSICAL EXAM:
VITALS: 98.2 PO 128 / 74 L Lying 76 18 96 Ra
Weight: 81.2 kg
GEN: Comfortable

Brief Hospital Course:
She was treated with IV diuretics and her breathing improved. Her warfarin was continued.

Medications on Admission:
1. Warfarin 5 mg PO DAILY
2. Furosemide 20 mg PO DAILY

Discharge Medications:
1. Warfarin 5 mg Tablet Sig: One (1) Tablet PO DAILY (Daily).
Disp:*30 Tablet(s)* Refills:*2*
2. Furosemide 40 mg PO BID
3. Metoprolol Succinate XL 50 mg PO DAILY
4. Acetaminophen 650 mg PO Q6H:PRN pain

Discharge Disposition:
Home

Discharge Diagnosis:
Acute on chronic heart failure

Discharge Condition:
Stable

Followup Instructions:
___
"""

MEDS = NOTE.split("Discharge Medications:\n", 1)[1].split("\n\nDischarge Disposition", 1)[0]
ANSWER_KEY = ("You were admitted because fluid built up in your lungs. We gave you medicine to "
              "remove the extra fluid and you are breathing better now.")


def makeRow(hadmId: int, leak: bool = False) -> dict:
    modelInput = NOTE + ("\nActivity:\n" + ANSWER_KEY if leak else "")
    return {
        "note_id": f"N{hadmId}", "subject_id": str(hadmId + 1000), "hadm_id": str(hadmId),
        "curr_service": "MED", "admittime": "2180-01-01 10:00:00",
        "dischtime": "2180-01-05 12:00:00", "lengthOfStayDays": "4",
        "modelInput": modelInput, "refInstructions": ANSWER_KEY,
        "dischargeMedsSection": MEDS, "allergiesSection": "Penicillins / Shellfish Derived\n ",
        "dispositionSection": "Home", "dischargeDiagnoses": ["Acute on chronic heart failure",
                                                              "Atrial fibrillation"],
    }


@pytest.fixture
def cohort() -> list[dict]:
    return [makeRow(20000001), makeRow(20000002), makeRow(20000003, leak=True)]


SECTION_TEXT = {
    "What happened in the hospital": "You came to the hospital because you were short of breath. "
                                     "We gave you medicine to remove extra fluid.",
    "What to do over the next few days": "Weigh yourself every morning. Take furosemide 40 mg by "
                                         "mouth twice a day. Rest and limit salt.",
    "When to get help right away": "Call 911 if you have chest pain or trouble breathing.",
    "Your follow-up": "See your heart doctor in one week. Call the Cardiology Clinic at 555-0142.",
}


class FakeClient(OllamaClient):
    """Stands in for Ollama. Records every prompt so tests can inspect what the model saw."""

    def __init__(self, loop: bool = False, dropFacts: bool = False, inventNumbers: bool = False,
                 fixOnRetry: bool = False):
        super().__init__(Settings(dbPath=None, ollamaUrl="http://fake", model="medgemma",
                                  numCtx=16384, temperature=0, repeatLastN=512,
                                  repeatPenalty=1.1, requestTimeout=5))
        self.prompts: list[str] = []
        self.loop = loop
        self.dropFacts = dropFacts
        self.inventNumbers = inventNumbers
        self.fixOnRetry = fixOnRetry

    def listModels(self) -> list[str]:
        return ["gemma3:latest", "medgemma:latest"]

    def complete(self, prompt, model, *, prefill=None, stop=None, maxTokens=900):
        self.prompts.append(prompt)
        if prompt.startswith("Rewrite each numbered line"):
            block = prompt.split("LINES:\n", 1)[1].split("\n\nREWRITTEN LINES:", 1)[0]
            retry = self.fixOnRetry and "Your last try" in prompt
            out = []
            for line in block.splitlines():
                number, text = line.split(". ", 1)
                rewrite = self.simplify(text, clean=retry).removeprefix("Sure! Here it is:\n")
                out.append(f"{number}. {rewrite}")
            return Completion(text="Sure! Here they are:\n" + "\n".join(out), promptTokens=200,
                              outputTokens=40, durationMs=50)
        if prompt.startswith("Rewrite this part"):
            original = prompt.split("TEXT:\n", 1)[1].split("\n\nREWRITTEN TEXT:", 1)[0]
            retry = self.fixOnRetry and "Your last try" in prompt
            return Completion(text=self.simplify(original, clean=retry), promptTokens=200,
                              outputTokens=40, durationMs=50)
        header = re.search(r"Section: (.+?):", prompt)
        if header:
            body = SECTION_TEXT[header.group(1)]
            if self.loop:
                body += (" Weigh yourself every morning before breakfast." * 5)
            return Completion(text=(prefill or "") + body, promptTokens=2100, outputTokens=60,
                              durationMs=100)
        text = "Okay, here are your instructions:\n\n" + "\n\n".join(
            f"{h}:\n{t}" for h, t in SECTION_TEXT.items())
        return Completion(text=text, promptTokens=2400, outputTokens=200, durationMs=300)

    def simplify(self, text: str, clean: bool = False) -> str:
        """Shorten words and sentences. With dropFacts, also lose any numbers (unless clean)."""
        out = (text.replace("hospital because you were short of breath", "hospital. You could not breathe well")
                   .replace("medicine to remove extra fluid", "medicine. It took out extra water")
                   .replace("Weigh yourself every morning", "Weigh yourself each morning"))
        if self.dropFacts and not clean:
            out = re.sub(r"\d+", "", out)
        if self.inventNumbers and not clean:
            out += " Call us at 555-1234 or come in at 9:00."
        return "Sure! Here it is:\n" + out
