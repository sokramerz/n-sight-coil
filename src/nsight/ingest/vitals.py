"""Vital signs from the note's Physical Exam section.

MIMIC discharge notes keep vitals as text, usually an admission exam and often a
discharge exam, written either with labels ("T 98.1 BP 120/80 HR 72") or as a bare
row in a fixed order ("VS: 98.1 120/80 72 18 97% RA"). A value is only returned when
it can be tied to one vital: labeled, unambiguous on its own (blood pressure,
temperature), or part of a complete bare row. Ranges ("HR 60-80") are skipped.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from nsight.ingest.segmentation import NEXT_HEADER

EXAM_SECTION = re.compile(rf"\nPhysical Exam[ \t]*:(.*?){NEXT_HEADER}", re.DOTALL | re.IGNORECASE)

DISCHARGE_MARK = re.compile(r"discharge\s+(?:physical\s+)?(?:exam(?:ination)?|pe)\b|"
                            r"(?:exam(?:ination)?|pe)\s+(?:on|at|upon|prior to)\s+discharge|"
                            r"day of discharge", re.IGNORECASE)
ADMISSION_MARK = re.compile(r"admi(?:ssion|t)\s+(?:physical\s+)?(?:exam(?:ination)?|pe)\b|"
                            r"(?:exam(?:ination)?|pe)\s+(?:on|at|upon)\s+admi(?:ssion|t)|"
                            r"^\s*on admission\b", re.IGNORECASE | re.MULTILINE)

VITALS_LINE = re.compile(r"(?:^|\n|:)[ \t]*(?:VS|V/S|Vitals?|Vital Signs)[ \t]*[:\-]?[ \t]*(.+)", re.IGNORECASE)
# the vitals line ends where the next exam heading starts ("GEN:", "General:")
NEXT_EXAM_LINE = re.compile(r"\n[ \t]*[A-Za-z/ ]{2,20}:")

NUMBER = r"(\d{2,3}(?:\.\d)?)"
RANGE_AFTER = r"(?![\d.])(?!\s*-\s*\d)"
BP_VALUE = r"(\d{2,3})\s*/\s*(\d{2,3})"
TEMP_LABEL = r"(?:Tc|Tcurrent|Tcurr|T|Temp(?:erature)?)"
LABELED = {
    "temperature": re.compile(rf"(?<![A-Za-z]){TEMP_LABEL}\s*[:=]?\s*{NUMBER}{RANGE_AFTER}", re.IGNORECASE),
    "bloodPressure": re.compile(rf"\bBP\s*[:=]?\s*{BP_VALUE}{RANGE_AFTER}", re.IGNORECASE),
    "heartRate": re.compile(rf"\b(?:HR|P|Pulse|Heart rate)\s*[:=]?\s*{NUMBER}{RANGE_AFTER}", re.IGNORECASE),
    "breathingRate": re.compile(rf"\b(?:RR|R|Resp(?:irations)?|Respiratory rate)\s*[:=]?\s*{NUMBER}{RANGE_AFTER}",
                                re.IGNORECASE),
    "oxygen": re.compile(rf"\b(?:O2\s*sat(?:uration)?|SpO2|SaO2|O2|Sat|Pulse ox)\s*[:=]?\s*{NUMBER}\s*%?{RANGE_AFTER}",
                         re.IGNORECASE),
}
WEIGHT = re.compile(r"\b(?:Wt|Weight|Discharge weight|Weight on discharge)\s*[:=]?\s*(\d{2,3}(?:\.\d)?)\s*(kg|lbs?|pounds)\b",
                    re.IGNORECASE)
DISCHARGE_WEIGHT = re.compile(r"(?:discharge weight|weight (?:on|at) discharge)\s*[:=]?\s*(\d{2,3}(?:\.\d)?)\s*"
                              r"(kg|lbs?|pounds)\b", re.IGNORECASE)
# a percentage on the vitals line can only be the oxygen level
PERCENT = re.compile(r"(?<![\d.])(\d{2,3})\s*%")
OXYGEN_SOURCE = re.compile(r"\b(RA|room air|\d(?:\.\d)?\s*L(?:PM)?\s*(?:NC|nasal cannula)?|NRB|BiPAP|CPAP)\b",
                           re.IGNORECASE)

# a bare row: temperature, blood pressure, then heart rate, breathing rate and oxygen,
# with the position and route words Epic adds ("PO", "L Lying") allowed in between
FILLER = r"(?:\s+(?:PO|Ax|Or|Oral|Tympanic|Temporal|Rectal|[LR]|Lying|Sitting|Standing|Supine))*"
BARE_ROW = re.compile(rf"^\s*(\d{{2,3}}\.\d){FILLER}[\s,]+{BP_VALUE}{FILLER}[\s,]+(\d{{2,3}}){FILLER}[\s,]+"
                      rf"(\d{{1,2}})[\s,]+(\d{{2,3}})\s*%?", re.IGNORECASE)

PLAIN = {
    "temperature": ("Temperature", "how warm your body is"),
    "bloodPressure": ("Blood pressure", "how hard your blood pushes on the walls of your blood vessels"),
    "heartRate": ("Heart rate", "how many times your heart beats in a minute"),
    "breathingRate": ("Breathing rate", "how many breaths you take in a minute"),
    "oxygen": ("Oxygen level", "how much oxygen your blood is carrying"),
    "weight": ("Weight", "your weight when you were measured in the hospital"),
}
ORDER = list(PLAIN)


@dataclass
class Vital:
    name: str
    label: str
    value: str
    meaning: str


@dataclass
class VitalSigns:
    timing: str  # "discharge", "admission" or "unstated"
    measurements: list[Vital] = field(default_factory=list)
    sourceLine: str = ""


def examSection(note: str | None) -> str | None:
    match = EXAM_SECTION.search("\n" + (note or ""))
    return match.group(1) if match else None


def splitExams(section: str) -> list[tuple[str, str]]:
    """[(timing, text)] for each exam in the section, in note order."""
    marks = sorted([(m.start(), "discharge") for m in DISCHARGE_MARK.finditer(section)] +
                   [(m.start(), "admission") for m in ADMISSION_MARK.finditer(section)])
    if not marks:
        return [("unstated", section)]
    exams = []
    if section[:marks[0][0]].strip():
        exams.append(("unstated", section[:marks[0][0]]))
    for i, (start, timing) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(section)
        exams.append((timing, section[start:end]))
    return exams


def vitalsLines(exam: str) -> list[str]:
    lines = []
    for match in VITALS_LINE.finditer(exam):
        rest = exam[match.start(1):]
        stop = NEXT_EXAM_LINE.search(rest)
        line = " ".join((rest[:stop.start()] if stop else rest).split())[:240]
        if line:
            lines.append(line)
    return lines


def inRange(name: str, value: float, extra: float | None = None) -> bool:
    if name == "temperature":
        return 93 <= value <= 107 or 34 <= value <= 42
    if name == "bloodPressure":
        return 60 <= value <= 260 and extra is not None and 30 <= extra <= 160 and extra < value
    if name == "heartRate":
        return 25 <= value <= 220
    if name == "breathingRate":
        return 6 <= value <= 60
    if name == "oxygen":
        return 60 <= value <= 100
    return False


def temperatureText(value: float) -> str:
    return f"{value:g} °F" if value > 50 else f"{value:g} °C"


def oxygenText(value: float, line: str, after: int) -> str:
    source = OXYGEN_SOURCE.search(line[after:after + 30])
    if not source:
        return f"{value:g}%"
    word = source.group(1)
    if word.lower() in ("ra", "room air"):
        return f"{value:g}% on room air"
    liters = re.match(r"(\d(?:\.\d)?)\s*L", word, re.IGNORECASE)
    if liters:
        return f"{value:g}% on {liters.group(1)} liters of oxygen"
    return f"{value:g}% on {word}"


def parseLine(line: str) -> dict[str, str]:
    """name -> display value, for the vitals that can be read with confidence."""
    found: dict[str, str] = {}
    bare = BARE_ROW.match(line)
    if bare:
        temp, sys_, dia, hr, rr, spo2 = (float(g) for g in bare.groups())
        if all([inRange("temperature", temp), inRange("bloodPressure", sys_, dia), inRange("heartRate", hr),
                inRange("breathingRate", rr), inRange("oxygen", spo2)]):
            return {"temperature": temperatureText(temp), "bloodPressure": f"{sys_:g}/{dia:g}",
                    "heartRate": f"{hr:g} beats per minute", "breathingRate": f"{rr:g} breaths per minute",
                    "oxygen": oxygenText(spo2, line, bare.end())}
    for name, pattern in LABELED.items():
        match = pattern.search(line)
        if not match:
            continue
        value = float(match.group(1))
        if name == "bloodPressure":
            if inRange(name, value, float(match.group(2))):
                found[name] = f"{value:g}/{float(match.group(2)):g}"
        elif inRange(name, value):
            found[name] = {"temperature": temperatureText(value),
                           "heartRate": f"{value:g} beats per minute",
                           "breathingRate": f"{value:g} breaths per minute",
                           "oxygen": oxygenText(value, line, match.end())}[name]
    if "oxygen" not in found:
        percent = PERCENT.search(line)
        if percent and inRange("oxygen", float(percent.group(1))):
            found["oxygen"] = oxygenText(float(percent.group(1)), line, percent.end())
    return found


def weightIn(text: str) -> str | None:
    match = WEIGHT.search(text)
    if not match:
        return None
    value, unit = float(match.group(1)), match.group(2).lower()
    if unit.startswith("kg"):
        return f"{value:g} kg ({value * 2.20462:.0f} lb)" if 25 <= value <= 300 else None
    return f"{value:g} lb" if 55 <= value <= 660 else None


def vitalSigns(note: str | None) -> VitalSigns | None:
    """The discharge exam's vitals, or the admission exam's when there is no discharge exam."""
    section = examSection(note)
    if not section:
        return None
    exams = splitExams(section)
    preference = {"discharge": 0, "unstated": 1, "admission": 2}
    for timing, exam in sorted(exams, key=lambda e: preference[e[0]]):
        line, values = next(((l, v) for l in vitalsLines(exam) if (v := parseLine(l))), (None, {}))
        weight = weightIn(exam)
        if not weight and timing != "admission":
            discharge = DISCHARGE_WEIGHT.search(note or "")
            weight = weightIn(f"Weight {discharge.group(1)} {discharge.group(2)}") if discharge else None
        if weight:
            values["weight"] = weight
        if values:
            return VitalSigns(timing=timing, sourceLine=line or "",
                              measurements=[Vital(name, PLAIN[name][0], values[name], PLAIN[name][1])
                                            for name in ORDER if name in values])
    return None
