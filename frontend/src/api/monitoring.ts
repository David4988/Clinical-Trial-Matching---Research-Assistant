/**
 * Phase 2 API client.
 *
 * Reuses the Phase 1 error convention: every non-2xx carries the structured
 * `{code, message, details}` body, surfaced as a `ScreeningApiError`.
 */

import { ScreeningApiError } from "./client";
import type { ApiError } from "../types/canonical";
import type {
  MonitoringCycleResult,
  MonitoringEvent,
  TrialOverview,
} from "../types/monitoring";

const BASE = "/api/monitoring";

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
