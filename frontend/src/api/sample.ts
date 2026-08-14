import type { Patient, Trial } from "../types/canonical";

/**
 * Canonical equivalent of fixtures/pdf/demo_screening.pdf.
 *
 * This is the demo's safety net: it goes to POST /screen and exercises the
 * whole engine without the PDF parser in the loop. If extraction ever breaks
 * on stage, the screening still runs.
 */

export const SAMPLE_PATIENT: Patient = {
  patient_id: "P-1042",
  age: 54,
  sex: "MALE",
  conditions: [
    { name: "Type 2 Diabetes", icd10: null, status: "ACTIVE" },
    { name: "Hypertension", icd10: null, status: "ACTIVE" },
    { name: "Stable Angina", icd10: null, status: "ACTIVE" },
  ],
  medications: [
    { name: "Metformin", status: "ACTIVE", duration_text: "5 months" },
  ],
  labs: [
    { name: "HbA1c", value: 7.1, unit: "%", observed_at: "12/09/2025" },
    { name: "HbA1c", value: 8.2, unit: "%", observed_at: "2026-03-11" },
    { name: "eGFR", value: 47, unit: "mL/min", observed_at: "2026-03-11" },
  ],
  notes: [],
};

export const SAMPLE_TRIAL: Trial = {
  trial_id: "CT-001",
  title: "Phase III Glycaemic Control Study in Type 2 Diabetes",
  criteria: [
    {
      criterion_id: "INC-01",
      kind: "INCLUSION",
      text: "Age between 18 and 65 years",
      rule: {
        type: "numeric",
        field: "age",
        op: "between",
        low: 18,
        high: 65,
        unit: "years",
      },
    },
    {
      criterion_id: "INC-02",
      kind: "INCLUSION",
      text: "Diagnosis: Type 2 Diabetes",
      rule: {
        type: "presence",
        domain: "condition",
        target: "Type 2 Diabetes",
        synonyms: [],
      },
    },
    {
      criterion_id: "INC-03",
      kind: "INCLUSION",
      text: "HbA1c between 7 and 10 %",
      rule: {
        type: "numeric",
        field: "lab:HbA1c",
        op: "between",
        low: 7,
        high: 10,
        unit: "%",
      },
    },
    {
      criterion_id: "INC-04",
      kind: "INCLUSION",
      text: "eGFR at least 45 mL/min",
      rule: {
        type: "numeric",
        field: "lab:eGFR",
        op: "gte",
        low: 45,
        high: null,
        unit: "mL/min",
      },
    },
    {
      criterion_id: "INC-05",
      kind: "INCLUSION",
      text: "Medication: Metformin",
      rule: {
        type: "presence",
        domain: "medication",
        target: "Metformin",
        synonyms: [],
      },
    },
    {
      criterion_id: "EXC-01",
      kind: "EXCLUSION",
      text: "Diagnosis: Severe cardiovascular disease",
      rule: {
        type: "presence",
        domain: "condition",
        target: "Severe cardiovascular disease",
        synonyms: [],
      },
    },
    {
      criterion_id: "EXC-02",
      kind: "EXCLUSION",
      text: "Prior exposure to investigational GLP-1 agonist within 6 months of screening",
      rule: null,
    },
  ],
};
