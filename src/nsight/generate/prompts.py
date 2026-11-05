"""Prompt templates for patient discharge instructions."""
from __future__ import annotations

ALL_TEXT_PROMPT = """You are writing the discharge instructions a patient will take home.

Use ONLY the information in the record below. Do not add advice, diagnoses, or
medications that do not appear in it.

You MUST include:
- Every medication in the discharge medication list, and why it is taken.
- Every allergy listed.
- What happened during this hospital stay, briefly.
- What to do over the next few days.
- What to watch for and when to seek help.
- Follow-up: who to contact and when.

Address the patient as "you". List every medication individually by name, one
per line, with what it is for. Do not summarize the medications as a group.

Do not include a patient name, date of birth, medical record number, or any
blank field to be filled in. Begin with what happened during the stay.

RECORD:
{record}

INSTRUCTIONS TO THE PATIENT:"""

TEMPLATED_PROMPT = """You are writing part of the discharge instructions a patient will take home.

The patient's medication list and allergies will be added separately, word for
word from the record. Do NOT list medications or allergies yourself.

Using ONLY the record below, write these four short sections, addressed to the
patient as "you":

What happened in the hospital:
What to do over the next few days:
When to get help right away:
Your follow-up:

Plain language. No title, no patient name, no date of birth, no blank fields.
Do not describe the record or say what it contains. Write to the patient.

RECORD:
{record}

"""

# record goes before the per-section part so ollama can reuse the cached prefix
SECTION_PROMPT = """You are writing discharge instructions a patient will take home.

Use ONLY the information in the record below. Do not add diagnoses, possible
causes, tests, or advice that do not appear in it. Do not speculate. Address
the patient as "you".

Write for an adult in short sentences and plain words, never baby talk. If a
medical word is needed, explain it in a few words. When telling the patient who
to call, name the team, clinic, or doctor; never write "call us". Do not add
general health advice; only write what this record supports.
{sourceRule}
RECORD:
{record}

Write ONLY the section below. Do not write any other section, and do not repeat
what the other sections cover. Do not give medicine doses or times; the full
medicine list with doses is added separately.

Section: {header}
{instruction}"""

INSTRUCTION_RULE = """
The record starts with what the patient's doctor wrote for them. That is the
most important source. Every instruction, treatment, test, appointment, date,
and warning sign in it must appear in the section it belongs to.
- Keep who does each thing exactly as the doctor wrote: who calls whom, who
  schedules what, who draws blood.
- Keep what is still to do as still to do. If the doctor says to take a
  medicine for 14 days, the patient starts or keeps taking it now.
- Do not add tasks, reasons, or explanations the doctor did not give.
- If the doctor's text says [redacted], write [redacted]. Never make up a date,
  time, name, phone number, or amount.
"""

# sections when the doctor's own instructions are part of the input.
# each one says what it leaves out, because sections are written one at a time
SECTIONS = (
    ("What happened in the hospital",
     "Write 2 to 4 short sentences as one paragraph, not a list: why the patient came in, the "
     "main diagnosis by name with a few plain words on what it means, and the main treatment. "
     "If the record says a condition is new, say so; never call a long-standing condition new. "
     "Leave out lab values and anything the patient has to do; later sections cover that."),
    ("What to do over the next few days",
     "Write a bulleted list of at most 8 actions, one per bullet, each starting with a verb. "
     "Include only what the record tells this patient to do: medicines to start, stop, or change "
     "(by name, without doses), how long to keep taking a medicine, and any home care, diet, "
     "activity, home nursing, or tests the record mentions. Do NOT include warning signs, the "
     "emergency room, or appointments; other sections cover those."),
    ("When to get help right away",
     "Write a bulleted list of at most 6 warning signs. Each bullet says the sign and what to do. "
     "Use the signs the doctor gave and keep the action the doctor gave for each one (for "
     "example, go to the emergency room). If the doctor gave none, list up to 5 signs that fit the "
     "patient's diagnoses, including bleeding signs if a new blood thinner was started, and say to "
     "go to the emergency room. Nothing else."),
    ("Your follow-up",
     "Write a bulleted list of appointments and scheduled tests only. For each: who, what for, "
     "when, and who sets it up (for example, 'The GI team will call you to schedule it'). Keep "
     "names, dates, and times exactly as written, including [redacted]. Do NOT repeat warning "
     "signs, medicines, or home care."),
)

# sections when drafting from the chart alone, without the doctor's instructions
CHART_SECTIONS = (
    ("What happened in the hospital",
     "In a few sentences, tell the patient why they came to the hospital and what was done."),
    ("What to do over the next few days",
     "Tell the patient what to do at home over the next few days."),
    ("When to get help right away",
     "Tell the patient which warning signs mean they should get help right away."),
    ("Your follow-up",
     "Tell the patient about their follow-up appointments and who to contact."),
)
SECTION_HEADERS = tuple(h for h, _ in SECTIONS)

SIMPLIFY_PROMPT = """Rewrite this part of a patient's discharge instructions so an adult who reads at a 6th grade level can follow it.

Rules:
- Keep every fact: every number, date, time, name, test, medicine, warning sign, and appointment.
- Keep who does what and when exactly as written, and keep what is still to do as still to do.
- Do not add anything that is not in the text.
- Use short sentences, under 15 words each.
- Use everyday adult words: stomach, stool, urine, sore. Never use baby talk like tummy, poop, or pee.
- If a medical word is needed, explain it in a few words in parentheses.
- Keep bullet points as bullet points, one per line.
- Talk to the patient as "you".
- Output only the rewritten text, with no heading and no introduction.
{note}
TEXT:
{text}

REWRITTEN TEXT:"""


SIMPLIFY_LINES_PROMPT = """Rewrite each numbered line of a patient's discharge instructions so an adult who reads at a 6th grade level can follow it.

Rules:
- Write exactly one numbered line for each numbered line below, with the same number. Never add new lines.
- Each line keeps every fact it had: every number, date, time, name, test, medicine, and warning sign.
- Do not add anything that is not in that line. No new advice, names, dates, or phone numbers.
- Keep who does what and when exactly as written.
- Use short sentences, under 15 words each. A line may hold more than one sentence.
- Use everyday adult words: stomach, stool, urine, sore. Never use baby talk like tummy, poop, or pee.
- If a medical word is needed, explain it in a few words in parentheses.
- Talk to the patient as "you". Never write "call us"; keep who to call as written.
- Output only the numbered lines.
{note}
LINES:
{text}

REWRITTEN LINES:"""

