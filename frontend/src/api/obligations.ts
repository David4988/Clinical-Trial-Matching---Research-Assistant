/** Obligation-layer API client. Reuses `ScreeningApiError` / `unwrap`'s
 * convention from `api/client.ts`, same pattern as `api/monitoring.ts`. */

import { API_BASE } from "./base";
import { ScreeningApiError } from "./client";
import type { ApiError } from "../types/canonical";
import type {
  Obligation,
  ObligationAction,
  ProposedAction,
  QueueResponse,
  ResponsibleParty,
} from "../types/obligations";

const BASE = `${API_BASE}/obligations`;

async function unwrap<T>(response: Response): Promise<T> {
  if (response.ok) return response.json() as Promise<T>;
  let error: ApiError = {
    code: `HTTP_${response.status}`,
    message: "The obligation service returned an unexpected response.",
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

async function post<T>(path: string, body: unknown = {}): Promise<T> {
  return unwrap<T>(
    await fetch(`${BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}

export function fetchQueue(trialId: string): Promise<QueueResponse> {
  return get<QueueResponse>(`/queue?trial_id=${encodeURIComponent(trialId)}`);
}

export function fetchObligation(obligationId: string): Promise<Obligation> {
  return get<Obligation>(`/${encodeURIComponent(obligationId)}`);
}

export function fetchLedger(obligationId: string): Promise<ObligationAction[]> {
  return get<ObligationAction[]>(`/${encodeURIComponent(obligationId)}/actions`);
}

export function fetchParties(trialId: string): Promise<ResponsibleParty[]> {
  return get<ResponsibleParty[]>(`/parties?trial_id=${encodeURIComponent(trialId)}`);
}

export function investigate(obligationId: string): Promise<ProposedAction> {
  return post<ProposedAction>(`/${encodeURIComponent(obligationId)}/investigate`);
}

export function dismissObligation(
  obligationId: string,
  reviewer: string,
  note: string,
): Promise<Obligation> {
  return post<Obligation>(`/${encodeURIComponent(obligationId)}/dismiss`, { reviewer, note });
}

export function approveProposal(
  proposalId: string,
  reviewer: string,
  note: string,
  channel?: string,
  editedSubject?: string,
  editedBody?: string,
): Promise<ProposedAction> {
  return post<ProposedAction>(`/proposals/${encodeURIComponent(proposalId)}/approve`, {
    reviewer,
    note,
    channel: channel || null,
    edited_subject: editedSubject || null,
    edited_body: editedBody || null,
  });
}

export function rejectProposal(
  proposalId: string,
  reviewer: string,
  note: string,
): Promise<ProposedAction> {
  return post<ProposedAction>(`/proposals/${encodeURIComponent(proposalId)}/reject`, {
    reviewer,
    note,
  });
}
