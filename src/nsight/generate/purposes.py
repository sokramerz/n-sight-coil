"""What each discharge medicine is for, in plain words.

Fixed text keyed by drug class, not model output. Each class has a one-line
purpose, and the conditions it is a standard treatment for. When one of those
conditions is in the patient's discharge diagnoses, the medicine says so ("Often
used for an irregular heartbeat, which is one of your diagnoses").
That's a fact about the drug class, not a claim about why this doctor prescribed it.

Written for the project; NEEDS CLINICIAN REVIEW like redflags.py and glossary.py.
"""
from __future__ import annotations

import re

from nsight.ingest.drugnames import candidates

# condition label -> pattern over the discharge diagnoses
CONDITIONS = {
    "afib": ("an irregular heartbeat (atrial fibrillation)", r"atrial fibrillation|atrial flutter|\bafib\b"),
    "clot": ("a blood clot", r"embolism|thrombosis|\bdvt\b|thrombus"),
    "heartFailure": ("heart failure", r"heart failure|cardiomyopathy"),
    "coronary": ("heart disease", r"myocardial infarction|coronary|angina|\bstemi\b|nstemi|stent"),
    "stroke": ("a stroke", r"stroke|cerebral infarction|transient ischemic"),
    "hypertension": ("high blood pressure", r"hypertension|hypertensive"),
    "diabetes": ("diabetes", r"diabetes|diabetic|hyperglycemia"),
    "copd": ("COPD (a long-term lung disease)", r"chronic obstructive|\bcopd\b|emphysema"),
    "asthma": ("asthma", r"asthma"),
    "ulcer": ("a stomach ulcer or stomach bleeding", r"ulcer|gastrointestinal hemorrhage|gi bleed|esophagitis"),
    "reflux": ("acid reflux", r"reflux|gerd"),
    "pylori": ("an H. pylori stomach infection", r"helicobacter|h\. ?pylori"),
    "cdiff": ("a C. diff infection", r"clostridi|c\. ?diff"),
    "pneumonia": ("pneumonia", r"pneumonia"),
    "uti": ("a urinary tract infection", r"urinary tract infection|cystitis|pyelonephritis"),
    "skin": ("a skin infection", r"cellulitis|abscess|wound infection"),
    "blood": ("an infection in the blood", r"bacteremia|sepsis|septicemia"),
    "liver": ("liver disease", r"cirrhosis|hepatic encephalopathy|ascites"),
    "transplant": ("an organ transplant", r"transplant"),
    "thyroid": ("low thyroid", r"hypothyroid"),
    "gout": ("gout", r"gout"),
    "seizure": ("a seizure disorder", r"seizure|epilep"),
    "anemia": ("anemia (low blood count)", r"anemia"),
    "smoking": ("tobacco use", r"tobacco|nicotine|smok"),
}

INFECTIONS = ("pylori", "cdiff", "pneumonia", "uti", "skin", "blood")

# class -> (purpose, conditions it treats)
CLASSES = {
    "anticoagulant": ("A blood thinner. It helps stop harmful blood clots from forming.", ("afib", "clot", "stroke")),
    "antiplatelet": ("Keeps blood cells called platelets from sticking together and forming clots.",
                     ("coronary", "stroke")),
    "loopDiuretic": ("A water pill. It removes extra fluid from your body.", ("heartFailure", "liver")),
    "thiazide": ("A water pill that lowers blood pressure.", ("hypertension",)),
    "aldosterone": ("A water pill that also protects the heart.", ("heartFailure", "liver", "hypertension")),
    "betaBlocker": ("Slows your heartbeat and lowers blood pressure.",
                    ("afib", "heartFailure", "coronary", "hypertension")),
    "aceArb": ("Lowers blood pressure and protects the heart and kidneys.",
               ("heartFailure", "hypertension", "diabetes", "coronary")),
    "arni": ("Helps a weak heart pump better and lowers blood pressure.", ("heartFailure",)),
    "ccb": ("Lowers blood pressure.", ("hypertension",)),
    "rateCcb": ("Slows your heartbeat and lowers blood pressure.", ("afib", "hypertension")),
    "statin": ("Lowers cholesterol to help prevent heart attacks and strokes.", ("coronary", "stroke", "diabetes")),
    "nitrate": ("Opens blood vessels to the heart to prevent chest pain.", ("coronary", "heartFailure")),
    "rhythm": ("Helps keep your heartbeat steady.", ("afib", "heartFailure")),
    "insulin": ("Insulin. It lowers your blood sugar.", ("diabetes",)),
    "diabetesPill": ("Lowers your blood sugar.", ("diabetes",)),
    "sglt2": ("Lowers blood sugar and helps a weak heart.", ("diabetes", "heartFailure")),
    "acidReducer": ("Lowers the acid your stomach makes.", ("ulcer", "reflux", "pylori")),
    "laxative": ("Helps you have regular bowel movements.", ()),
    "lactulose": ("Helps you have bowel movements and clears toxins that build up with liver disease.", ("liver",)),
    "antibiotic": ("An antibiotic. It fights infections caused by bacteria.", INFECTIONS),
    "steroid": ("A steroid. It calms swelling and inflammation.", ("copd", "asthma")),
    "rescueInhaler": ("Opens your airways quickly when you are short of breath.", ("copd", "asthma")),
    "dailyInhaler": ("A daily inhaler that keeps your airways open.", ("copd", "asthma")),
    "painReliever": ("Treats pain and fever.", ()),
    "opioid": ("A strong pain medicine (an opioid).", ()),
    "nervePain": ("Often used for nerve pain.", ("seizure",)),
    "potassium": ("A potassium supplement. Water pills can lower the potassium in your blood.", ()),
    "magnesium": ("A magnesium supplement.", ()),
    "iron": ("An iron supplement that helps your body make red blood cells.", ("anemia",)),
    "vitamin": ("A vitamin supplement.", ()),
    "calcium": ("A calcium supplement for your bones.", ()),
    "thyroid": ("Thyroid hormone.", ("thyroid",)),
    "immune": ("Calms the immune system so it does not attack a transplanted organ.", ("transplant",)),
    "nicotine": ("Gives a small steady dose of nicotine to help you quit smoking.", ("smoking",)),
    "nausea": ("Prevents nausea and vomiting.", ()),
    "uricAcid": ("Lowers uric acid to prevent gout attacks.", ("gout",)),
    "prostate": ("Helps you pass urine more easily.", ()),
    "antidepressant": ("Used for depression and anxiety.", ()),
    "antiseizure": ("Prevents seizures.", ("seizure",)),
    "bismuth": ("Protects the stomach lining. Part of the treatment for H. pylori.", ("pylori", "ulcer")),
}

DRUGS = {
    "anticoagulant": "apixaban, rivaroxaban, dabigatran, edoxaban, warfarin, enoxaparin, heparin",
    "antiplatelet": "acetylsalicylic acid, aspirin, clopidogrel, ticagrelor, prasugrel",
    "loopDiuretic": "furosemide, torsemide, torasemide, bumetanide",
    "thiazide": "hydrochlorothiazide, chlorthalidone",
    "aldosterone": "spironolactone, eplerenone",
    "betaBlocker": "metoprolol, carvedilol, atenolol, propranolol, labetalol, bisoprolol, nadolol",
    "aceArb": "lisinopril, enalapril, ramipril, captopril, benazepril, losartan, valsartan, irbesartan, olmesartan",
    "arni": "sacubitril",
    "ccb": "amlodipine, nifedipine, felodipine",
    "rateCcb": "diltiazem, verapamil",
    "statin": "atorvastatin, rosuvastatin, simvastatin, pravastatin, lovastatin",
    "nitrate": "isosorbide mononitrate, isosorbide dinitrate, isosorbide, nitroglycerin",
    "rhythm": "amiodarone, digoxin, sotalol, dofetilide",
    "insulin": "insulin glargine, insulin lispro, insulin aspart, insulin detemir, insulin degludec, insulin regular, insulin",
    "diabetesPill": "metformin, glipizide, glyburide, glimepiride, sitagliptin, linagliptin, pioglitazone",
    "sglt2": "empagliflozin, dapagliflozin, canagliflozin",
    "acidReducer": "pantoprazole, omeprazole, esomeprazole, lansoprazole, famotidine",
    "laxative": "sennosides, senna, docusate, polyethylene glycol, bisacodyl",
    "lactulose": "lactulose",
    "antibiotic": "cefepime, ceftriaxone, cephalexin, cefpodoxime, cefuroxime, cefazolin, amoxicillin, ampicillin, clavulanic acid, azithromycin, doxycycline, ciprofloxacin, levofloxacin, moxifloxacin, metronidazole, vancomycin, sulfamethoxazole, trimethoprim, nitrofurantoin, linezolid, clindamycin, piperacillin, meropenem, ertapenem, tetracycline, clarithromycin, daptomycin, rifaximin",
    "steroid": "prednisone, methylprednisolone, dexamethasone, hydrocortisone, prednisolone",
    "rescueInhaler": "salbutamol, albuterol, levalbuterol, ipratropium",
    "dailyInhaler": "tiotropium, fluticasone, salmeterol, budesonide, formoterol, umeclidinium",
    "painReliever": "acetaminophen",
    "opioid": "oxycodone, hydromorphone, morphine, tramadol, hydrocodone",
    "nervePain": "gabapentin, pregabalin",
    "potassium": "potassium chloride",
    "magnesium": "magnesium oxide",
    "iron": "ferrous sulfate anhydrous, ferrous sulfate, ferrous gluconate",
    "vitamin": "folic acid, thiamine, cholecalciferol, vitamin d, cyanocobalamin, multivitamin",
    "calcium": "calcium carbonate",
    "thyroid": "levothyroxine",
    "immune": "tacrolimus, mycophenolate mofetil, mycophenolic acid, cyclosporine, azathioprine",
    "nicotine": "nicotine",
    "nausea": "ondansetron",
    "uricAcid": "allopurinol, febuxostat",
    "prostate": "tamsulosin, finasteride",
    "antidepressant": "sertraline, escitalopram, citalopram, fluoxetine, paroxetine",
    "antiseizure": "levetiracetam, lamotrigine, phenytoin",
    "bismuth": "bismuth subsalicylate",
}

DRUG_CLASS = {name.strip(): cls for cls, names in DRUGS.items() for name in names.split(",")}


def drugClass(medName: str) -> str | None:
    for names in candidates(medName):
        classes = [DRUG_CLASS[n] for n in names if n in DRUG_CLASS]
        if classes:
            # a combination pill takes the class of its more specific part
            return "arni" if "arni" in classes else classes[0]
    return None


def matchedConditions(diagnoses: list[str]) -> set[str]:
    text = " ".join(diagnoses).lower()
    return {key for key, (_, pattern) in CONDITIONS.items() if re.search(pattern, text)}


def purposeFor(medName: str, diagnoses: list[str]) -> dict[str, str | None] | None:
    """{'purpose': ..., 'forCondition': ...} or None when the drug isn't on the list."""
    cls = drugClass(medName)
    if cls is None:
        return None
    purpose, treats = CLASSES[cls]
    present = matchedConditions(diagnoses)
    condition = next((CONDITIONS[c][0] for c in treats if c in present), None)
    reason = f"Often used for {condition}, which is one of your diagnoses." if condition else None
    return {"purpose": purpose, "forCondition": reason}
