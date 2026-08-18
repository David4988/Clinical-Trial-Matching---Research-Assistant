/**
 * Phase 2 API client.
 *
 * Reuses the Phase 1 error convention: every non-2xx carries the structured
 * `{code, message, details}` body, surfaced as a `ScreeningApiError`.
 */

import { API_BASE } from "./base";
import { ScreeningApiError } from "./client";
import type { ApiError } from "../types/canonical";
import type {
  InvestigatorAction,
  InvestigatorReview,
  ModelProvenance,
  MonitoringCycleResult,
  MonitoringEvent,
  TreatmentAssignment,
  TrialOverview,
} from "../types/monitoring";

const BASE = `${API_BASE}/monitoring`;

async function unwrap<T>(response: Response): Promise<T> {
  if (response.ok) return response.json() as Promise<T>;

  let error: ApiError = {
    code: `HTTP_${response.status}`,
    message: "The monitoring service returned an unexpected response.",
    details: [],
  };
  try {
    const body = await response.json();
    if (body?.error) error = body.error;
  } catch {
    // Body was not JSON — keep the generic error above.
  }
  throw new ScreeningApiError(error);
}

async function get<T>(path: string): Promise<T> {
  return unwrap<T>(await fetch(`${BASE}${path}`));
}

async function post<T>(path: string, body: unknown): Promise<T> {
  return unwrap<T>(
    await fetch(`${BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}

export function fetchOverview(trialId: string): Promise<TrialOverview> {
  return get<TrialOverview>(`/trials/${encodeURIComponent(trialId)}/overview`);
}

export function fetchLatestCycle(patientId: string): Promise<MonitoringCycleResult> {
  return get<MonitoringCycleResult>(
    `/patients/${encodeURIComponent(patientId)}/cycle`,
  );
}

export function fetchTimeline(patientId: string): Promise<MonitoringEvent[]> {
  return get<MonitoringEvent[]>(
    `/patients/${encodeURIComponent(patientId)}/timeline`,
  );
}

export function fetchCycles(patientId: string): Promise<MonitoringCycleResult[]> {
  return get<MonitoringCycleResult[]>(
    `/patients/${encodeURIComponent(patientId)}/cycles`,
  );
}

/** Populates the demo cohort by running the real pipeline for each patient. */
export function seedDemo(trialId: string): Promise<{ patients: unknown[] }> {
  return post(`/demo/seed`, { trial_id: trialId, seed: 7, windows: 5 });
}

/** What produced the risk verdicts this deployment is serving. */
export function fetchModel(): Promise<ModelProvenance> {
  return get<ModelProvenance>(`/model`);
}

/**
 * Enter Phase 2 from a screening result.
 *
 * No override is sent: when the screening is REVIEW_REQUIRED, the recorded
 * human review is what authorises enrolment, and the backend reads it from the
 * screening itself. Passing one here would create a second approval competing
 * with the reviewer's.
 */
export function registerTreatment(
  screeningResultId: string,
  drugName: string,
): Promise<TreatmentAssignment> {
  return post<TreatmentAssignment>(`/treatments`, {
    screening_result_id: screeningResultId,
    drug_name: drugName,
  });
}

export function fetchTreatment(treatmentId: string): Promise<TreatmentAssignment> {
  return get<TreatmentAssignment>(`/treatments/${encodeURIComponent(treatmentId)}`);
}

export function recordDose(
  treatmentId: string,
  dose: {
    amount: number;
    unit: string;
    route?: string;
    administered_by?: string;
  },
): Promise<TreatmentAssignment> {
  return post<TreatmentAssignment>(
    `/treatments/${encodeURIComponent(treatmentId)}/doses`,
    dose,
  );
}

/**
 * Play one synthetic observation window for one participant and return the
 * resulting cycle. The same ingest-then-cycle pipeline the cohort seeder runs,
 * so an advanced participant is not on a special code path.
 */
export function advanceMonitoring(
  patientId: string,
  trialId: string,
  windowIndex: number,
  windows = 5,
): Promise<MonitoringCycleResult> {
  return post<MonitoringCycleResult>(
    `/patients/${encodeURIComponent(patientId)}/advance`,
    { trial_id: trialId, window_index: windowIndex, windows },
  );
}

export function recordInvestigatorReview(
  patientId: string,
  action: InvestigatorAction,
  reviewer: string,
  note: string,
  cycleId?: string,
): Promise<InvestigatorReview> {
  return post<InvestigatorReview>(
    `/patients/${encodeURIComponent(patientId)}/investigator-review`,
    { action, reviewer, note, cycle_id: cycleId },
  );
}

export function fetchInvestigatorReviews(
  patientId: string,
): Promise<InvestigatorReview[]> {
  return get<InvestigatorReview[]>(
    `/patients/${encodeURIComponent(patientId)}/investigator-reviews`,
  );
}
