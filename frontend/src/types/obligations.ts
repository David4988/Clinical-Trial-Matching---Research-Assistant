/** Obligation-layer canonical types, mirroring `types/monitoring.ts` and the
 * backend's `schema/obligations.py`. */

import type { Evidence } from "./canonical";

export type ObligationStatus = "OPEN" | "AWAITING_RESPONSE" | "RESOLVED" | "DISMISSED";
export type ObligationPriority = "LOW" | "MEDIUM" | "HIGH" | "URGENT";
export type ObligationType = "MISSING_LAB_EVIDENCE" | "MISSING_REQUIRED_OBSERVATION";
export type ProposalStatus = "DRAFT" | "APPROVED" | "REJECTED" | "EXECUTED" | "FAILED";
export type ActorKind = "SYSTEM" | "AGENT" | "RESEARCHER";

export interface ObligationResolution {
  kind: "SATISFIED" | "DISMISSED" | "SUPERSEDED";
  by: string;
  note: string;
  at: string;
}

export interface Obligation {
  obligation_id: string;
  obligation_key: string;
  trial_id: string;
  patient_id: string;
  type: ObligationType;
  status: ObligationStatus;
  priority: ObligationPriority;
  requirement_ref: string;
  requirement_text: string;
  protocol_id: string;
  source_ref: string;
  detector_source: string;
  title: string;
  detail: string;
  evidence: Evidence[];
  first_detected_at: string;
  last_confirmed_at: string;
  due_at: string | null;
  responsible_party_id: string | null;
  escalation_count: number;
  action_count: number;
  last_action_at: string | null;
  resolved_at: string | null;
  resolution: ObligationResolution | null;
}

export interface ObligationAction {
  action_id: string;
  obligation_id: string;
  seq: number;
  kind: string;
  occurred_at: string;
  actor_kind: ActorKind;
  actor_name: string | null;
  channel: string | null;
  recipient_party_id: string | null;
  ref_id: string | null;
  note: string;
}

export interface ProposalProvenance {
  generated_by: string;
  provider_kind: "TEMPLATE" | "LOCAL" | "HOSTED";
  model_name: string | null;
  prompt_version: string | null;
  latency_ms: number | null;
  degraded: boolean;
  unresolved: string[];
}

export interface ProposalDecision {
  outcome: "APPROVED" | "REJECTED";
  reviewer: string;
  note: string;
  decided_at: string;
  edited_subject: string | null;
  edited_body: string | null;
}

export interface ProposalExecution {
  executed_at: string;
  provider: string;
  channel: string;
  delivery_status: "UNKNOWN" | "SENT" | "DELIVERED" | "READ" | "FAILED";
  error: string | null;
}

export interface ProposedAction {
  proposal_id: string;
  obligation_ids: string[];
  trial_id: string;
  patient_ids: string[];
  action_type: string;
  status: ProposalStatus;
  recipient_party_id: string;
  channel: string;
  subject: string;
  body: string;
  reason: string;
  evidence: Evidence[];
  template_name: string | null;
  provenance: ProposalProvenance;
  created_at: string;
  decision: ProposalDecision | null;
  execution: ProposalExecution | null;
}

export interface ResponsibleParty {
  party_id: string;
  display_name: string;
  role: string;
  preferred_channel: string;
}

export interface QueueItem {
  obligation_id: string;
  patient_id: string;
  site_id: string | null;
  type: ObligationType;
  status: ObligationStatus;
  priority: ObligationPriority;
  title: string;
  reason: string;
  due_at: string | null;
  responsible_party: { party_id: string; display_name: string } | null;
  age_days: number;
  awaiting_days: number | null;
  escalation_count: number;
  attempt_count: number;
  last_action_at: string | null;
  pending_proposal_id: string | null;
  needs_human_decision: boolean;
}

export interface QueueResponse {
  trial_id: string;
  generated_at: string;
  counts: { total: number; needs_decision: number; awaiting_response: number };
  items: QueueItem[];
}
