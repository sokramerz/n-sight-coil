"""Fictional admissions in MIMIC-IV discharge note format.

Written by hand for this project. No real patient data: every name, date, value and
event is invented. Because nothing here comes from MIMIC, documents generated from
these cases can be shared and reviewed outside the credentialed environment.
"""
from __future__ import annotations

HEADER = """Name: ___ Unit No: ___
Admission Date: ___ Discharge Date: ___
Date of Birth: ___ Sex: {sex}
Service: MEDICINE
"""


def note(sex: str, body: str) -> str:
    return HEADER.format(sex=sex) + body.strip() + "\n"


CASES = [
    # 1. kidney transplant, line infection, long IV antibiotic course, new imaging
    dict(
        hadm_id=90000001, sex="M",
        diagnoses=["Pseudomonas bacteremia", "Tunneled dialysis catheter infection",
                   "Microscopic hematuria", "Kidney transplant recipient"],
        allergies="Sulfa (Sulfonamide Antibiotics)",
        disposition="Home With Service",
        body="""
Allergies:
Sulfa (Sulfonamide Antibiotics)

Chief Complaint:
Fevers and chills

History of Present Illness:
Mr. ___ is a ___ year old man with ESRD s/p deceased donor kidney transplant (___) on
tacrolimus, mycophenolate and prednisone, with a tunneled right IJ catheter left in place
after transplant, who presented with 2 days of fevers to 102.8 and rigors after flushing
his line at home.

Physical Exam:
ADMISSION PHYSICAL EXAM:
VS: 101.9 118/64 104 20 96% RA
GEN: Ill appearing, rigors
LINE: Right IJ tunneled catheter, mild erythema at exit site

DISCHARGE PHYSICAL EXAM:
VITALS: 98.2 PO 126 / 72 L Lying 78 18 98 Ra
GEN: Well appearing
LINE: Left arm PICC clean, dry and intact

Brief Hospital Course:
# Pseudomonas bacteremia: Blood cultures from the line and peripherally grew Pseudomonas
aeruginosa sensitive to cefepime. Line was felt to be the source. Started on cefepime 2 g
IV q12h. Surveillance cultures cleared on hospital day 3. TTE without vegetation. Plan
14 day course from first negative culture, end date ___. PICC placed in the left arm for
home antibiotics. Tunneled catheter to be removed by transplant surgery as outpatient,
it is no longer needed for dialysis.
# Hematuria: UA with 25 RBCs, no clear cause. Renal ultrasound of the transplant was
unremarkable. Transplant nephrology recommends outpatient MRI abdomen to evaluate.
# Transplant: Tacrolimus trough 6.1 on admission, goal 5-8, dose unchanged. Creatinine
stable at 1.4.

TRANSITIONAL ISSUES:
- Cefepime 2 g IV q12h through ___ via PICC, VNA to manage
- Weekly CBC, BMP, tacrolimus trough while on cefepime, results to Dr. ___ (transplant)
- Tunneled line removal with transplant surgery, appointment pending
- Outpatient MRI abdomen for hematuria, patient to call radiology to schedule
- PICC removal after last antibiotic dose

Medications on Admission:
1. Tacrolimus 3 mg PO Q12H
2. Mycophenolate Mofetil 500 mg PO BID
3. PredniSONE 5 mg PO DAILY
4. Amlodipine 5 mg PO DAILY
5. Aspirin 81 mg PO DAILY

Discharge Medications:
1. CefePIME 2 g IV Q12H Duration: 11 Days RX *cefepime 2 gram 2 g IV q12h Disp #*22 Vial Refills:*0
2. Tacrolimus 3 mg PO Q12H
3. Mycophenolate Mofetil 500 mg PO BID
4. PredniSONE 5 mg PO DAILY
5. Amlodipine 5 mg PO DAILY
6. Aspirin 81 mg PO DAILY
7. Sodium Chloride 0.9% Flush 10 mL IV DAILY and PRN, line flush
8. Outpatient Lab Work CBC, BMP, tacrolimus trough weekly ICD-10: T86.10 Contact: Dr. ___ Fax: ___

Discharge Disposition:
Home With Service

Discharge Diagnosis:
Pseudomonas bacteremia
Tunneled catheter infection
Microscopic hematuria

Discharge Condition:
Mental Status: Clear and coherent. Ambulatory - Independent.

Followup Instructions:
Transplant Nephrology, Dr. ___, ___ at 10:30 AM
Transplant Surgery for line removal, office will call
""",
        ref="""Dear Mr. ___,

It was a pleasure taking care of you at ___. You came in with fevers and chills. We found
bacteria growing in your blood, most likely from the catheter in your chest. You will need
IV antibiotics (cefepime) through the PICC line in your arm until ___. A visiting nurse
will help you with this and will draw blood once a week.

The catheter in your chest is no longer needed. The transplant surgery team will call you
to set up a time to take it out.

We found a small amount of blood in your urine. Please call radiology at ___ to schedule
an MRI of your abdomen.

Please call your transplant team or come to the emergency room if you have a fever over
100.4, chills, redness or pus at the PICC site, or less urine than usual.

We wish you all the best,
Your ___ Team""",
    ),
    # 2. heart failure exacerbation with diuretic change, weights, salt and fluid limits
    dict(
        hadm_id=90000002, sex="F",
        diagnoses=["Acute on chronic systolic heart failure", "Hypertension", "Chronic kidney disease stage 3"],
        allergies="Lisinopril (cough)",
        disposition="Home",
        body="""
Allergies:
Lisinopril

Chief Complaint:
Shortness of breath, leg swelling

History of Present Illness:
Ms. ___ is a ___ year old woman with HFrEF (EF 30%), HTN and CKD 3 who presents with
1 week of worsening dyspnea on exertion, 3 pillow orthopnea and 8 lb weight gain after
running out of furosemide and eating at a family event.

Physical Exam:
ADMISSION EXAM:
Vitals: T 97.9 BP 152/88 HR 92 RR 22 O2 sat 91% on 2L NC
GEN: Short of breath speaking in sentences
EXT: 2+ pitting edema to the knees

DISCHARGE EXAM:
Vitals: T 98.1 BP 128/76 HR 74 RR 16 O2 96% RA
Weight: 79.8 kg (admission 84.6 kg)
EXT: Trace edema at the ankles

Brief Hospital Course:
# Acute on chronic systolic heart failure: Diuresed with IV furosemide with 9 lb weight
loss. Transitioned to torsemide 40 mg daily given poor response to oral furosemide.
Discharge weight 168 lb. Metoprolol succinate continued. Sacubitril-valsartan started
at 24-26 mg BID after 36 hour washout (no ACE inhibitor at home). Counseled on 2 g sodium
diet and 1.5 L fluid restriction.
# CKD: Creatinine peaked at 1.9 with diuresis, 1.6 at discharge (baseline 1.5).

TRANSITIONAL ISSUES:
- New torsemide 40 mg daily, furosemide stopped
- New sacubitril-valsartan, recheck BMP in 1 week
- Daily weights, call if up more than 3 lb in a day or 5 lb in a week
- Discharge weight 168 lb
- Heart failure clinic within 7 to 10 days

Medications on Admission:
1. Furosemide 40 mg PO DAILY
2. Metoprolol Succinate XL 50 mg PO DAILY
3. Atorvastatin 40 mg PO QPM
4. Potassium Chloride 20 mEq PO DAILY

Discharge Medications:
1. Torsemide 40 mg PO DAILY RX *torsemide 20 mg 2 tablet(s) by mouth daily Disp #*60 Tablet Refills:*1
2. Sacubitril-Valsartan (24mg-26mg) 1 TAB PO BID
3. Metoprolol Succinate XL 50 mg PO DAILY
4. Atorvastatin 40 mg PO QPM
5. Potassium Chloride 20 mEq PO DAILY
6. Outpatient Lab Work BMP in 1 week ICD-10: I50.23

Discharge Disposition:
Home

Discharge Diagnosis:
Acute on chronic systolic heart failure

Discharge Condition:
Stable, ambulatory.

Followup Instructions:
Heart Failure Clinic, Dr. ___, ___ at 2:00 PM
PCP Dr. ___ within 2 weeks
""",
        ref="""Dear Ms. ___,

You were admitted because fluid built up in your lungs and legs from heart failure. We
removed the fluid with IV water pills and you lost 9 pounds.

We made these changes to your medicines:
- STOP furosemide (Lasix)
- START torsemide 40 mg once a day. This is your new water pill.
- START Entresto (sacubitril-valsartan) twice a day for your heart

Weigh yourself every morning after you use the bathroom. Your weight when you left was 168
pounds. Call the heart failure clinic if you gain more than 3 pounds in a day or 5 pounds
in a week. Eat less than 2 grams of salt a day and drink no more than 1.5 liters of fluid.

Please get blood work in 1 week to check your kidneys and potassium.

Sincerely,
Your ___ Team""",
    ),
    # 3. COPD flare with steroid taper, new home oxygen, smoking
    dict(
        hadm_id=90000003, sex="M",
        diagnoses=["COPD exacerbation", "Chronic hypoxemic respiratory failure", "Tobacco use"],
        allergies="No Known Allergies / Adverse Drug Reactions",
        disposition="Home With Service",
        body="""
Allergies:
No Known Allergies / Adverse Drug Reactions

Chief Complaint:
Shortness of breath

History of Present Illness:
Mr. ___ is a ___ year old man with severe COPD (FEV1 38%) and active tobacco use (40 pack
years) who presents with 4 days of increased cough, sputum and wheezing after a viral URI.

Physical Exam:
PHYSICAL EXAM ON DISCHARGE:
VS: Tmax 99.4 Tc 98.6 BP 110-134/60-72 HR 88 RR 18 SpO2 92% 2L NC
GEN: Comfortable on home oxygen
LUNGS: Scattered expiratory wheezes, improved

Brief Hospital Course:
# COPD exacerbation: Treated with nebulizers, prednisone 40 mg daily and azithromycin.
Viral panel positive for rhinovirus. Wheezing improved. Ambulatory saturation 86% on room
air, 92% on 2 L, so home oxygen was arranged. Inhaler technique reviewed. Started on
tiotropium in addition to his albuterol.
# Tobacco use: Counseled for 10 minutes. Started nicotine patch 21 mg.

TRANSITIONAL ISSUES:
- Prednisone 40 mg daily, last dose ___ (5 day total course)
- Azithromycin last dose ___
- New home O2 2 L with activity and sleep, reassess need at follow up
- Referral to pulmonary rehab placed
- Smoking cessation, nicotine patch

Medications on Admission:
1. Albuterol Inhaler 2 PUFF IH Q4H:PRN wheezing, shortness of breath

Discharge Medications:
1. PredniSONE 40 mg PO DAILY Duration: 2 Days
2. Azithromycin 250 mg PO DAILY Duration: 1 Day
3. Tiotropium Bromide 1 CAP IH DAILY
4. Albuterol Inhaler 2 PUFF IH Q4H:PRN wheezing, shortness of breath
5. Nicotine Patch 21 mg TD DAILY
6. Home Oxygen 2 L continuous with exertion and sleep via nasal cannula, Dx: J44.1, length of need 99 months

Discharge Disposition:
Home With Service

Discharge Diagnosis:
COPD exacerbation

Discharge Condition:
Stable.

Followup Instructions:
Pulmonology, Dr. ___, ___ at 9:00 AM
""",
        ref="""Dear Mr. ___,

You were in the hospital because your COPD flared up after a cold. We treated you with
breathing treatments, steroids (prednisone) and an antibiotic.

- Take prednisone for 2 more days and the antibiotic for 1 more day.
- Use your new inhaler (tiotropium) every day, even when you feel well.
- Use oxygen at 2 liters when you walk around and when you sleep.
- The most important thing you can do for your lungs is to stop smoking. Use the nicotine
patch every day.
- We referred you to pulmonary rehab. They will call you.

Come back to the emergency department if you are too short of breath to speak, your lips
turn blue, or you have chest pain.

We wish you the best,
Your ___ Team""",
    ),
    # 4. bleeding ulcer, stop NSAIDs, H. pylori treatment, repeat scope
    dict(
        hadm_id=90000004, sex="F",
        diagnoses=["Upper GI bleed", "Gastric ulcer", "Helicobacter pylori infection", "Acute blood loss anemia"],
        allergies="Penicillins",
        disposition="Home",
        body="""
Allergies:
Penicillins

Chief Complaint:
Black stools, lightheadedness

History of Present Illness:
Ms. ___ is a ___ year old woman taking ibuprofen 800 mg TID for knee pain who presents
with 3 days of black tarry stools and lightheadedness. Hgb 6.9 on arrival (baseline 12).

Physical Exam:
VS: 98.4 104/62 96 16 99%RA
GEN: Pale, alert
ABD: Soft, mild epigastric tenderness

Brief Hospital Course:
# Upper GI bleed: Transfused 2 units PRBC. EGD showed a 1 cm gastric body ulcer with a
visible vessel, treated with clips and epinephrine. No further bleeding. Hgb stable at 9.1
for 48 hours. Pantoprazole 40 mg IV BID, transitioned to PO BID for 8 weeks.
# H. pylori: Biopsy positive. Penicillin allergic, so started bismuth quadruple therapy
for 14 days.
# NSAID use: Ibuprofen stopped. Advised acetaminophen for knee pain, no more than 3 g/day.

TRANSITIONAL ISSUES:
- Bismuth quadruple therapy for 14 days, last day ___
- Pantoprazole BID for 8 weeks then daily
- Repeat EGD in 8 weeks to confirm healing, GI will schedule
- CBC in 1 week
- No NSAIDs

Medications on Admission:
1. Ibuprofen 600 mg PO TID:PRN knee pain
2. Acetaminophen 500 mg PO Q6H:PRN pain

Discharge Medications:
1. Pantoprazole 40 mg PO Q12H
2. Bismuth Subsalicylate 524 mg PO QID Duration: 14 Days
3. Metronidazole 500 mg PO TID Duration: 14 Days
4. Tetracycline 500 mg PO QID Duration: 14 Days
5. Acetaminophen 650 mg PO Q6H:PRN knee pain, do not exceed 3 grams per day
6. Ferrous Sulfate 325 mg PO DAILY
7. Outpatient Lab Work CBC on ___ ICD-10: K25.4 Results to PCP Dr. ___

Discharge Disposition:
Home

Discharge Diagnosis:
Bleeding gastric ulcer
H. pylori infection

Discharge Condition:
Stable.

Followup Instructions:
GI, Dr. ___, repeat endoscopy, office will call
PCP, Dr. ___, ___ at 11:15 AM
""",
        ref="""Dear Ms. ___,

You were admitted with bleeding from an ulcer in your stomach. The ulcer was caused by
ibuprofen and by an infection called H. pylori. We gave you 2 units of blood and closed
the ulcer with clips during an endoscopy.

Please do not take ibuprofen, naproxen, aspirin or other NSAIDs. You can take Tylenol for
your knee pain, up to 3 grams a day.

Take all 4 medicines for the H. pylori infection for the full 14 days. Take pantoprazole
twice a day for 8 weeks.

Get a blood count checked in 1 week. The GI doctors will call you to schedule a repeat
endoscopy in 8 weeks.

Return to the emergency room if you have black or bloody stools, vomit blood, or feel
faint.

Sincerely,
Your ___ Team""",
    ),
    # 5. DKA with new insulin regimen and supplies
    dict(
        hadm_id=90000005, sex="M",
        diagnoses=["Diabetic ketoacidosis", "Type 1 diabetes mellitus"],
        allergies="No Known Allergies / Adverse Drug Reactions",
        disposition="Home",
        body="""
Allergies:
No Known Allergies / Adverse Drug Reactions

Chief Complaint:
Nausea, vomiting, abdominal pain

History of Present Illness:
Mr. ___ is a ___ year old man with type 1 diabetes since age 12 who ran out of insulin
glargine 5 days ago because of a pharmacy insurance problem. Presented with vomiting,
glucose 512, anion gap 26, beta-hydroxybutyrate 6.8.

Physical Exam:
ON ADMISSION:
VS: T 99.1 BP 100/60 HR 122 RR 28 SpO2 99% RA
GEN: Deep rapid breathing, dry mucous membranes

Brief Hospital Course:
# DKA: Treated with IV insulin drip and fluids per protocol. Gap closed in 14 hours.
Transitioned to glargine 22 units at bedtime and lispro with meals per carb ratio 1:10 plus
correction scale. Insurance issue resolved by social work, 90 day supply sent. Diabetes
educator reviewed sick day rules and ketone testing.
# A1c 9.8.

TRANSITIONAL ISSUES:
- New glargine dose 22 units qHS (previously 18)
- Lispro 1 unit per 10 g carbs plus correction scale
- Check glucose before meals and at bedtime, bring log to endocrine
- Sick day rules: never stop glargine, check ketones if glucose over 250
- Endocrinology follow up within 2 weeks

Medications on Admission:
1. Glargine 18 Units Bedtime
Humalog 1 Unit per 12 grams carbohydrate with meals, plus sliding scale

Discharge Medications:
1. Glargine 22 Units Bedtime
Humalog 1 Unit per 10 grams carbohydrate with meals, plus sliding scale
2. Glucometer 1 each Use as directed
3. Blood Glucose Test Strips Check 4 times daily Disp #*200 Strip Refills:*3
4. Ketone urine test strips Check if glucose over 250

Discharge Disposition:
Home

Discharge Diagnosis:
Diabetic ketoacidosis

Discharge Condition:
Stable.

Followup Instructions:
Endocrinology, Dr. ___, ___ at 3:45 PM
""",
        ref="""Dear Mr. ___,

You were admitted with diabetic ketoacidosis (DKA) because you ran out of your long-acting
insulin. Your insulin is now covered for 90 days.

- Take glargine 22 units every night. This is a higher dose than before.
- Take Humalog with meals: 1 unit for every 10 grams of carbs, plus your correction scale.
- Check your sugar before each meal and at bedtime and write it down.
- Never skip your glargine, even if you are sick and not eating.
- If your sugar is over 250, check your urine for ketones.

Go to the emergency room if you are vomiting and cannot keep fluids down, or your ketones
are moderate or large.

Bring your sugar log to your endocrinology appointment.

Take care,
Your ___ Team""",
    ),
    # 6. sparse clinician instructions: tests the fallback when the doctor wrote little
    dict(
        hadm_id=90000006, sex="F",
        diagnoses=["Left lower extremity cellulitis", "New atrial fibrillation"],
        allergies="Codeine (nausea)",
        disposition="Home",
        body="""
Allergies:
Codeine

Chief Complaint:
Red, painful left leg

History of Present Illness:
Ms. ___ is a ___ year old woman with obesity and venous stasis who presents with 3 days of
spreading redness and pain of the left shin. Found to be in atrial fibrillation with rates
to 130 on arrival, new diagnosis.

Physical Exam:
Discharge PE: VS: afebrile, BP 122/70, P 64, R 14, 98% RA
EXT: Left lower leg erythema receding from marked borders

Brief Hospital Course:
# Cellulitis: Treated with IV cefazolin, redness receded from marked border. Transitioned
to cephalexin 500 mg QID to complete 7 days total. Leg elevation encouraged.
# New atrial fibrillation: Likely triggered by infection. Rate controlled with metoprolol.
CHA2DS2-VASc 3, started apixaban 5 mg BID after discussion of risks and benefits. TTE with
normal EF. TSH normal.

TRANSITIONAL ISSUES:
- Cephalexin through ___
- New apixaban, new metoprolol
- Cardiology follow up for atrial fibrillation, consider rhythm control

Medications on Admission:
None.

Discharge Medications:
1. Cephalexin 500 mg PO Q6H Duration: 3 Days
2. Apixaban 5 mg PO BID
3. Metoprolol Succinate XL 50 mg PO DAILY

Discharge Disposition:
Home

Discharge Diagnosis:
Cellulitis
Atrial fibrillation

Discharge Condition:
Stable.

Followup Instructions:
Cardiology, Dr. ___, office will call
PCP, Dr. ___, ___ at 1:30 PM
""",
        ref="""Dear Ms. ___,

You were admitted for a skin infection of your leg. Please take your medications as
prescribed and follow up with your doctors.

Your ___ Team""",
    ),
]


def syntheticRows() -> list[dict]:
    """Rows shaped like cohortV2.json, ready for Store.loadCohort."""
    rows = []
    for case in CASES:
        text = note(case["sex"], case["body"])
        meds = text.split("Discharge Medications:\n", 1)[1].split("\n\nDischarge Disposition", 1)[0]
        rows.append({
            "note_id": f"SYN-{case['hadm_id']}", "subject_id": str(case["hadm_id"] + 1),
            "hadm_id": str(case["hadm_id"]), "curr_service": "MED",
            "admittime": "2180-01-01 10:00:00", "dischtime": "2180-01-05 12:00:00",
            "lengthOfStayDays": "4", "modelInput": text, "refInstructions": case["ref"],
            "dischargeMedsSection": meds, "allergiesSection": case["allergies"],
            "dispositionSection": case["disposition"], "dischargeDiagnoses": case["diagnoses"],
        })
    return rows
