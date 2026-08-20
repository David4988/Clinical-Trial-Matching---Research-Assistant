/**
 * Mirrors backend/app/schema/monitoring*.py — the frontend half of the Phase 2
 * contract. If a Pydantic model changes, change it here in the same commit.
 *
 * Note what is absent by design: `RiskAssessment` has no action field, and
 * `PatientState` has no risk field. The frontend cannot render a clinical
 * action attributed to the risk model, because no such field exists.
 */

import type { Evidence, Severity } from "./canonical";

export type RiskLevel = "GREEN" | "AMBER" | "RED" | "UNKNOWN";
export type TrendDirection = "RISING" | "FALLING" | "STABLE" | "INSUFFICIENT_DATA";
export type NextDoseDecision = "PROCEED" | "REVIEW_REQUIRED" | "HOLD";
export type DataQualityStatus = "OK" | "DEGRADED" | "UNTRUSTWORTHY";
export type TreatmentStatus = "ACTIVE" | "COMPLETED" | "ON_HOLD" | "WITHDRAWN";
export type MeasurementType =
  | "HEART_RATE"
  | "SYSTOLIC_BP"
  | "DIASTOLIC_BP"
  | "SPO2"
  | "TEMPERATURE"
  | "RESPIRATORY_RATE";

export interface Observation {
  observation_id: string;
  patient_id: string;
  trial_id: string;
  recorded_at: string;
  source: string;
  measurement_type: MeasurementType;
  value: number;
  unit: string;
  device_id: string | null;
  quality_note: string | null;
}

export interface DoseAdministration {
  dose_number: number;
  administered_at: string;
  amount: number;
  unit: string;
  route: string | null;
  administered_by: string | null;
  note: string | null;
}

export type InvestigatorAction =
  | "ACKNOWLEDGE"
  | "CONTINUE_MONITORING"
  | "HOLD_TREATMENT";

/**
 * A named investigator's decision about one monitoring cycle.
 *
 * Deliberately a separate vocabulary from `Intervention.action`: an
 * intervention is what the protocol requires, this is what a person decided
 * after reading it. Recording one changes no risk level.
 */
export interface InvestigatorReview {
  review_id: string;
  patient_id: string;
  trial_id: string;
  cycle_id: string;
  action: InvestigatorAction;
  reviewer: string;
  note: string;
  reviewed_at: string;
  risk_level: RiskLevel;
  treatment_status_after: TreatmentStatus | null;
}

/** Provenance for whatever produced the risk verdicts on screen. */
export interface ModelProvenance {
  provider: string;
  model_version: string;
  live_inference: boolean;
  /**
   * Copied through from the artifact's own metadata, so several fields arrive
   * as nested objects rather than strings. Typing them as strings is what
   * previously let an object reach React as a child and blank the page.
   */
  artifact?: {
    model_version: string | null;
    feature_version: string | null;
    features: string[] | null;
    estimator: { class?: string; n_estimators?: number } | null;
    training_cohort: {
      source?: string;
      total_patients?: number;
      cohort_windows?: number;
      fitted_rows?: number;
    } | null;
    scoring: { anomaly_score?: string; decimals?: number } | null;
    created_at: string | null;
    model_sha256: string | null;
    trained_with?: Record<string, string> | null;
  };
  artifact_error?: string;
}

export interface EligibilityOverride {
  approved_by: string;
  reason: string;
  approved_at: string;
  screening_status: string;
}

export interface TreatmentAssignment {
  treatment_id: string;
  patient_id: string;
  trial_id: string;
  screening_result_id: string;
  drug_name: string;
  course_label: string | null;
  status: TreatmentStatus;
  registered_at: string;
  doses: DoseAdministration[];
  override: EligibilityOverride | null;
}

export interface MeasurementSummary {
  measurement_type: MeasurementType;
  unit: string | null;
  baseline: number | null;
  current: number | null;
  latest_at: string | null;
  delta_from_baseline: number | null;
  trend: TrendDirection;
  slope_per_hour: number | null;
  sample_count: number;
  is_stale: boolean;
}

export interface DataQualityFlag {
  code: string;
  severity: Severity;
  message: string;
  measurement_types: MeasurementType[];
}

export interface DataQuality {
  status: DataQualityStatus;
  flags: DataQualityFlag[];
}

export interface AdverseEvent {
  event_id: string;
  patient_id: string;
  term: string;
  severity: string;
  onset_at: string;
  resolved_at: string | null;
}

export interface PatientState {
  patient_id: string;
  trial_id: string;
  as_of: string;
  treatment: TreatmentAssignment | null;
  measurements: MeasurementSummary[];
  recent_observations: Observation[];
  active_adverse_events: AdverseEvent[];
  data_quality: DataQuality;
  observation_count: number;
}

export interface ContributingFactor {
  factor: string;
  detail: string;
  weight: number;
  measurement_type: MeasurementType | null;
}

export interface RiskAssessment {
  assessment_id: string;
  patient_id: string;
  assessed_at: string;
  level: RiskLevel;
  score: number;
  confidence: number;
  prediction_horizon_hours: number;
  contributing_factors: ContributingFactor[];
  likely_patterns: string[];
  provider: string;
  model_version: string;
  degraded: boolean;
}

export interface FeatureEvidence {
  feature_name: string;
  raw_value: number | null;
  transformed_value: number;
  model_weight: number;
  contribution: number;
  direction: "POSITIVE" | "NEGATIVE";
  objective_description: string;
}

export interface PredictiveRiskAssessment {
  provider: string;
  model_version: string;
  feature_version: string;
  horizon_hours: number;
  score: number | null;
  threshold: number;
  predicted_deterioration: boolean | null;
  data_quality_state: string;
  evidence: FeatureEvidence[];
  evaluated_at: string;
  artifact_checksum: string;
}

export interface XAIExplanationRequest {
  model_name: string;
  model_version: string;
  signal_type: string;
  risk_state: string;
  score: number | null;
  score_semantics: string;
  horizon_hours: number | null;
  evidence: Array<Record<string, unknown>>;
  deterministic_explanation: string | null;
}

export interface XAIExplanation {
  explanation_text: string;
  evidence_references: string[];
  generated_at: string;
  model_name: string;
  prompt_version: string;
  status: "OK" | "UNAVAILABLE" | "INVALID_RESPONSE";
}

/** The trust gate's output: what was applied, what the model said, and why. */
export interface EffectiveRisk {
  level: RiskLevel;
  provider_level: RiskLevel;
  gated: boolean;
  reason: string;
}

export interface RiskTransition {
  from_level: RiskLevel | null;
  to_level: RiskLevel;
  occurred_at: string;
  trigger: string;
}

export interface Intervention {
  intervention_id: string;
  raised_at: string;
  action: string;
  severity: Severity;
  rationale: string;
  protocol_rule_id: string;
  risk_level: RiskLevel;
  monitoring_interval_minutes: number | null;
  evidence: Evidence[];
}

export interface Notification {
  notification_id: string;
  audience: string;
  channel: string;
  subject: string;
  body: string;
  created_at: string;
  delivered_at: string | null;
  delivery_provider: string | null;
}

export interface NextDoseCriterion {
  criterion_id: string;
  description: string;
  satisfied: boolean | null;
  detail: string;
}

export interface NextDoseAssessment {
  assessment_id: string;
  treatment_id: string;
  assessed_at: string;
  decision: NextDoseDecision;
  proposed_dose_number: number | null;
  criteria: NextDoseCriterion[];
  reasons: string[];
  blocking_criteria: string[];
  risk_level: RiskLevel;
  data_quality_status: DataQualityStatus;
  decision_support_only: boolean;
}

export interface MonitoringCycleResult {
  cycle_id: string;
  patient_id: string;
  trial_id: string;
  generated_at: string;
  state: PatientState;
  risk: RiskAssessment;
  effective_risk: EffectiveRisk;
  transition: RiskTransition | null;
  interventions: Intervention[];
  notifications: Notification[];
  next_dose: NextDoseAssessment | null;
  summary: string;
  early_warning: PredictiveRiskAssessment | null;
}

export interface MonitoringEvent {
  event_id: string;
  patient_id: string;
  occurred_at: string;
  event_type: string;
  summary: string;
  ref_id: string | null;
  payload: Record<string, unknown>;
}

export interface OverviewPatient {
  patient_id: string;
  treatment_id: string;
  drug_name: string;
  treatment_status: string;
  dose_count: number;
  risk_level: RiskLevel;
  risk_score: number | null;
  gated: boolean;
  next_dose: NextDoseDecision | null;
  last_assessed_at: string | null;
  data_quality: DataQualityStatus | null;
}

export interface TrialOverview {
  trial_id: string;
  protocol_id: string;
  protocol_label: string;
  total_patients: number;
  active_treatments: number;
  risk_counts: Record<RiskLevel, number>;
  requiring_attention: OverviewPatient[];
  patients: OverviewPatient[];
}
