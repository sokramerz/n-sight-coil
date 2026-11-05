-- cohort v2: MED-service admissions with Discharge Instructions held out.
-- sections end only at real MIMIC headers, so Disp: and Activity: lines don't cut them off.

WITH lastService AS (
  SELECT
    hadm_id,
    curr_service,
    ROW_NUMBER() OVER (PARTITION BY hadm_id ORDER BY transfertime DESC) AS rn
  FROM `physionet-data.mimiciv_3_1_hosp.services`
),

notes AS (
  SELECT d.note_id, d.subject_id, d.hadm_id, d.charttime, d.text
  FROM `physionet-data.mimiciv_note.discharge` d
  WHERE LENGTH(d.text) BETWEEN 2000 AND 40000
    AND STRPOS(d.text, 'Discharge Instructions:') > 0
    AND STRPOS(d.text, 'Discharge Medications:') > 0
),

sections AS (
  SELECT
    n.*,
    REGEXP_EXTRACT(n.text, r'(?s)\nDischarge Instructions:[ \t]*(.*?)(?:\n(?:Name|Unit No|Admission Date|Discharge Date|Date of Birth|Sex|Service|Allergies|Attending|Chief Complaint|Major Surgical or Invasive Procedure|History of Present Illness|Past Medical History|Social History|Family History|Physical Exam|Pertinent Results|Brief Hospital Course|Medications on Admission|Discharge Medications|Discharge Disposition|Discharge Diagnosis|Discharge Condition|Discharge Instructions|Followup Instructions)[ \t]*:|\z)') AS refInstructions,
    REGEXP_EXTRACT(n.text, r'(?s)\nDischarge Medications:[ \t]*(.*?)(?:\n(?:Name|Unit No|Admission Date|Discharge Date|Date of Birth|Sex|Service|Allergies|Attending|Chief Complaint|Major Surgical or Invasive Procedure|History of Present Illness|Past Medical History|Social History|Family History|Physical Exam|Pertinent Results|Brief Hospital Course|Medications on Admission|Discharge Medications|Discharge Disposition|Discharge Diagnosis|Discharge Condition|Discharge Instructions|Followup Instructions)[ \t]*:|\z)') AS dischargeMedsSection,
    REGEXP_EXTRACT(n.text, r'(?s)\nAllergies:[ \t]*(.*?)(?:\n(?:Name|Unit No|Admission Date|Discharge Date|Date of Birth|Sex|Service|Allergies|Attending|Chief Complaint|Major Surgical or Invasive Procedure|History of Present Illness|Past Medical History|Social History|Family History|Physical Exam|Pertinent Results|Brief Hospital Course|Medications on Admission|Discharge Medications|Discharge Disposition|Discharge Diagnosis|Discharge Condition|Discharge Instructions|Followup Instructions)[ \t]*:|\z)') AS allergiesSection,
    REGEXP_EXTRACT(n.text, r'(?s)\nDischarge Disposition:[ \t]*(.*?)(?:\n(?:Name|Unit No|Admission Date|Discharge Date|Date of Birth|Sex|Service|Allergies|Attending|Chief Complaint|Major Surgical or Invasive Procedure|History of Present Illness|Past Medical History|Social History|Family History|Physical Exam|Pertinent Results|Brief Hospital Course|Medications on Admission|Discharge Medications|Discharge Disposition|Discharge Diagnosis|Discharge Condition|Discharge Instructions|Followup Instructions)[ \t]*:|\z)') AS dispositionSection,
    REGEXP_REPLACE(n.text, r'(?s)\nDischarge Instructions:[ \t]*.*?((?:\n(?:Name|Unit No|Admission Date|Discharge Date|Date of Birth|Sex|Service|Allergies|Attending|Chief Complaint|Major Surgical or Invasive Procedure|History of Present Illness|Past Medical History|Social History|Family History|Physical Exam|Pertinent Results|Brief Hospital Course|Medications on Admission|Discharge Medications|Discharge Disposition|Discharge Diagnosis|Discharge Condition|Discharge Instructions|Followup Instructions)[ \t]*:|\z))', r'\1') AS modelInput
  FROM notes n
),

diagnoses AS (
  SELECT
    di.hadm_id,
    ARRAY_AGG(dd.long_title ORDER BY di.seq_num LIMIT 15) AS dischargeDiagnoses
  FROM `physionet-data.mimiciv_3_1_hosp.diagnoses_icd` di
  JOIN `physionet-data.mimiciv_3_1_hosp.d_icd_diagnoses` dd
    ON dd.icd_code = di.icd_code AND dd.icd_version = di.icd_version
  GROUP BY di.hadm_id
)

SELECT
  s.note_id,
  s.subject_id,
  s.hadm_id,
  ls.curr_service,
  a.admittime,
  a.dischtime,
  DATE_DIFF(DATE(a.dischtime), DATE(a.admittime), DAY) AS lengthOfStayDays,
  s.modelInput,
  s.refInstructions,
  s.dischargeMedsSection,
  s.allergiesSection,
  s.dispositionSection,
  dx.dischargeDiagnoses,
  LENGTH(s.modelInput)      AS inputChars,
  LENGTH(s.refInstructions) AS refChars,
  ARRAY_LENGTH(REGEXP_EXTRACT_ALL(s.dischargeMedsSection, r'(?m)^\s*\d+\s*[\.\)]')) AS medEntries
FROM sections s
JOIN lastService ls ON ls.hadm_id = s.hadm_id AND ls.rn = 1
JOIN `physionet-data.mimiciv_3_1_hosp.admissions` a ON a.hadm_id = s.hadm_id
LEFT JOIN diagnoses dx ON dx.hadm_id = s.hadm_id
WHERE ls.curr_service = 'MED'
  AND s.refInstructions IS NOT NULL
  AND s.dischargeMedsSection IS NOT NULL
  AND LENGTH(s.refInstructions) BETWEEN 200 AND 6000
  AND STRPOS(s.modelInput, 'Discharge Instructions:') = 0
ORDER BY FARM_FINGERPRINT(CAST(s.hadm_id AS STRING))
LIMIT 500;