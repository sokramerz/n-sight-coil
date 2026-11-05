-- first pass cohort (superseded by cohortV2.sql, kept for reproducibility)

WITH lastService AS (
  SELECT
    hadm_id,
    curr_service,
    ROW_NUMBER() OVER (PARTITION BY hadm_id ORDER BY transfertime DESC) AS rn
  FROM `physionet-data.mimiciv_3_1_hosp.services`
),

notes AS (
  SELECT
    d.note_id,
    d.subject_id,
    d.hadm_id,
    d.charttime,
    d.text
  FROM `physionet-data.mimiciv_note.discharge` d
  WHERE LENGTH(d.text) BETWEEN 2000 AND 40000
    AND STRPOS(d.text, 'Discharge Instructions:') > 0
    AND STRPOS(d.text, 'Discharge Medications:') > 0
),

sections AS (
  SELECT
    n.*,
    -- held-out reference: what the clinician actually wrote for the patient
    REGEXP_EXTRACT(
      n.text,
      r'(?s)\nDischarge Instructions:\s*(.*?)\n[A-Z][A-Za-z][A-Za-z /\-]*:'
    ) AS refInstructions,

    -- fact inventory sources, parsed downstream in Python
    REGEXP_EXTRACT(
      n.text,
      r'(?s)\nDischarge Medications:\s*(.*?)\n[A-Z][A-Za-z][A-Za-z /\-]*:'
    ) AS dischargeMedsSection,
    REGEXP_EXTRACT(
      n.text,
      r'(?s)\nAllergies:\s*(.*?)\n[A-Z][A-Za-z][A-Za-z /\-]*:'
    ) AS allergiesSection,
    REGEXP_EXTRACT(
      n.text,
      r'(?s)\nDischarge Disposition:\s*(.*?)\n[A-Z][A-Za-z][A-Za-z /\-]*:'
    ) AS dispositionSection,

    -- model input: same note with the target section removed
    REGEXP_REPLACE(
      n.text,
      r'(?s)\nDischarge Instructions:\s*.*?(\n[A-Z][A-Za-z][A-Za-z /\-]*:)',
      r'\1'
    ) AS modelInput
  FROM notes n
),

diagnoses AS (
  SELECT
    di.hadm_id,
    ARRAY_AGG(
      dd.long_title ORDER BY di.seq_num LIMIT 15
    ) AS dischargeDiagnoses
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
  LENGTH(s.refInstructions) AS refChars

FROM sections s
JOIN lastService ls
  ON ls.hadm_id = s.hadm_id AND ls.rn = 1
JOIN `physionet-data.mimiciv_3_1_hosp.admissions` a
  ON a.hadm_id = s.hadm_id
LEFT JOIN diagnoses dx
  ON dx.hadm_id = s.hadm_id

WHERE ls.curr_service = 'MED'
  -- both extractions succeeded, so the regex actually matched
  AND s.refInstructions IS NOT NULL
  AND s.dischargeMedsSection IS NOT NULL
  AND LENGTH(s.refInstructions) BETWEEN 200 AND 6000
  -- the strip worked: the target section is gone from the input
  AND STRPOS(s.modelInput, 'Discharge Instructions:') = 0

ORDER BY FARM_FINGERPRINT(CAST(s.hadm_id AS STRING))   -- deterministic shuffle
LIMIT 500;