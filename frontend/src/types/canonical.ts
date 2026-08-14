/**
 * Mirrors backend/app/schema. This file is the frontend half of the canonical
 * contract — if a Pydantic model changes, change it here in the same commit.
 */

export type CriterionStatus = "PASS" | "FAIL" | "UNKNOWN";
export type OverallStatus = "ELIGIBLE" | "INELIGIBLE" | "REVIEW_REQUIRED";
export type CriterionKind = "INCLUSION" | "EXCLUSION";
export type AIVerdict = "SUPPORTED" | "NOT_SUPPORTED" | "AMBIGUOUS";
export type Severity = "INFO" | "WARN";
export type NumericOp = "gte" | "gt" | "lte" | "lt" | "eq" | "between";

export interface Evidence {
  source_type: string;
  locator: string | null;
  snippet: string | null;
  note: string | null;
}

export interface Condition {
  name: string;
  icd10: string | null;
  status: string;
}

export interface Medication {
  name: string;
  status: string;
  duration_text: string | null;
}

export interface LabResult {
  name: string;
  value: number;
  unit: string;
  observed_at: string | null;
}

export interface Patient {
  patient_id: string;
  age: number | null;
  age_source?: Evidence | null;
  sex: string;
  conditions: Condition[];
  medications: Medication[];
  labs: LabResult[];
  notes: string[];
}

export interface NumericRule {
  type: "numeric";
  field: string;
  op: NumericOp;
  low: number | null;
  high: number | null;
  unit: string | null;
}

export interface PresenceRule {
  type: "presence";
  domain: "condition" | "medication";
  target: string;
  synonyms: string[];
}

export type Rule = NumericRule | PresenceRule;

export interface Criterion {
  criterion_id: string;
  kind: CriterionKind;
  text: string;
  rule: Rule | null;
}

export interface Trial {
  trial_id: string;
  title: string;
  criteria: Criterion[];
}

export interface CriterionResult {
  criterion_id: string;
  kind: CriterionKind;
  text: string;
  status: CriterionStatus;
  raw_match: boolean | null;
  expected: string;
  observed: string | null;
  evidence: Evidence[];
  evaluator: string;
}

export interface HeuristicFlag {
  code: string;
  severity: Severity;
  message: string;
  criterion_ids: string[];
}

export interface AICriterionOpinion {
  criterion_id: string;
  verdict: AIVerdict;
  confidence: number;
  rationale: string;
}

export interface AIAnalysis {
  provider: string;
  opinions: AICriterionOpinion[];
  summary: string;
  degraded: boolean;
}

export interface Disagreement {
  criterion_id: string;
  rule_status: CriterionStatus;
  ai_verdict: AIVerdict;
  description: string;
}

export interface ScreeningResult {
  result_id: string;
  patient: Patient;
  trial: Trial;
  overall_status: OverallStatus;
  criteria_results: CriterionResult[];
  passed_count: number;
  failed_count: number;
  unknown_count: number;
  rule_coverage: number;
  heuristic_flags: HeuristicFlag[];
  ai_analysis: AIAnalysis | null;
  disagreements: Disagreement[];
  status_reason: string;
  generated_at: string;
}

export interface ApiError {
  code: string;
  message: string;
  details: string[];
}
