"""SQLAlchemy Core table definitions.

Core, not the ORM — see `docs/FINAL_IMPLEMENTATION_PLAN.md` §9.8. The domain
objects are already validated, lifecycled Pydantic models; a second object
layer with an identity map and lazy loading would be a second source of truth
for what an `Obligation` (or a `Patient`, or a `MonitoringCycleResult`) is.
This module only knows column shapes. `db/mappers.py` is the only module that
knows a column name maps to a Pydantic field.

Phase 1 defines Group A (hybrid document tables) and Group B (fully
normalised, reused domain) from §9.4 of the final plan. Group C (the
obligation operational core) is added in Phase 2 onward, in the same
`MetaData` object, so Alembic autogeneration sees one schema throughout.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

from .engine import schema_name

metadata = MetaData(schema=schema_name())

# -- Group A: hybrid document tables ----------------------------------------
# Real, indexed columns for what is filtered/sorted on; one JSONB `document`
# column holding the validated Pydantic model. `model_dump(mode="json")` in,
# `model_validate` out — mechanical, matching what the JSON repositories
# already do.

patients = Table(
    "patients",
    metadata,
    Column("patient_id", String, primary_key=True),
    Column("document", JSONB, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

trials = Table(
    "trials",
    metadata,
    Column("trial_id", String, primary_key=True),
    Column("title", String, nullable=False),
    Column("document", JSONB, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

screening_results = Table(
    "screening_results",
    metadata,
    Column("result_id", String, primary_key=True),
    Column("patient_id", String, ForeignKey("patients.patient_id"), nullable=False),
    Column("trial_id", String, ForeignKey("trials.trial_id"), nullable=False),
    Column("overall_status", String, nullable=False),
    Column("generated_at", DateTime(timezone=True), nullable=False),
    Column("document", JSONB, nullable=False),
    Index("ix_screening_results_patient_trial_generated", "patient_id", "trial_id", "generated_at"),
)

treatments = Table(
    "treatments",
    metadata,
    Column("treatment_id", String, primary_key=True),
    Column("patient_id", String, nullable=False),
    Column("trial_id", String, ForeignKey("trials.trial_id"), nullable=False),
    Column(
        "screening_result_id",
        String,
        ForeignKey("screening_results.result_id"),
        nullable=False,
    ),
    Column("status", String, nullable=False),
    Column("registered_at", DateTime(timezone=True), nullable=False),
    Column("document", JSONB, nullable=False),
    Index("ix_treatments_trial_status", "trial_id", "status"),
    Index("ix_treatments_patient", "patient_id"),
)

monitoring_cycles = Table(
    "monitoring_cycles",
    metadata,
    Column("cycle_id", String, primary_key=True),
    Column("patient_id", String, nullable=False),
    Column("trial_id", String, ForeignKey("trials.trial_id"), nullable=False),
    Column("generated_at", DateTime(timezone=True), nullable=False),
    Column("risk_level", String, nullable=True),
    Column("document", JSONB, nullable=False),
    Index("ix_monitoring_cycles_patient_generated", "patient_id", "generated_at"),
)

# -- Group B: fully normalised, reused domain -------------------------------

observations = Table(
    "observations",
    metadata,
    Column("observation_id", String, primary_key=True),
    Column("patient_id", String, nullable=False),
    Column("trial_id", String, ForeignKey("trials.trial_id"), nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    Column("source", String, nullable=False),
    Column("measurement_type", String, nullable=False),
    Column("value", Float, nullable=False),
    Column("unit", String, nullable=False),
    Column("device_id", String, nullable=True),
    Column("quality_note", String, nullable=True),
    Index("ix_observations_patient_recorded", "patient_id", "recorded_at"),
    Index(
        "ix_observations_patient_type_recorded",
        "patient_id",
        "measurement_type",
        "recorded_at",
    ),
)

adverse_events = Table(
    "adverse_events",
    metadata,
    Column("event_id", String, primary_key=True),
    Column("patient_id", String, nullable=False),
    Column("trial_id", String, ForeignKey("trials.trial_id"), nullable=False),
    Column("term", String, nullable=False),
    Column("severity", String, nullable=False),
    Column("onset_at", DateTime(timezone=True), nullable=False),
    Column("resolved_at", DateTime(timezone=True), nullable=True),
    Column("reported_by", String, nullable=True),
    Column("note", String, nullable=True),
    Index("ix_adverse_events_patient_onset", "patient_id", "onset_at"),
)

monitoring_events = Table(
    "monitoring_events",
    metadata,
    Column("event_id", String, primary_key=True),
    Column("patient_id", String, nullable=False),
    Column("trial_id", String, ForeignKey("trials.trial_id"), nullable=False),
    Column("event_type", String, nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("summary", String, nullable=False),
    Column("ref_id", String, nullable=True),
    Column("payload", JSONB, nullable=False, server_default="{}"),
    Index("ix_monitoring_events_patient_occurred", "patient_id", "occurred_at"),
)

notifications = Table(
    "notifications",
    metadata,
    Column("notification_id", String, primary_key=True),
    Column("patient_id", String, nullable=False),
    Column("trial_id", String, ForeignKey("trials.trial_id"), nullable=False),
    Column("channel", String, nullable=False),
    # `audience` mirrors the actual `Notification.audience` field (the final
    # plan's §9.4 sketch names this column `severity`, generically written
    # before the real schema was re-checked against the repository; the real
    # `Notification` model has no `severity` field, so this column follows
    # the model that exists rather than the sketch — see
    # docs/FINAL_IMPLEMENTATION_PLAN.md §3's own rule to build against the
    # actual repository).
    Column("audience", String, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    # `proposal_id` (§9.4's Group C reference) is added by a later Alembic
    # revision once `proposed_actions` exists (Phase 7) — the migration
    # ordering note in the final plan applies literally here.
    Column("document", JSONB, nullable=False),
    # NEW: the reference `proposed_actions` (below) fills once execution
    # exists. Nullable — most notifications are still monitoring alerts.
    Column(
        "proposal_id",
        String,
        ForeignKey("proposed_actions.proposal_id", name="fk_notifications_proposal_id"),
        nullable=True,
    ),
    Index("ix_notifications_patient_created", "patient_id", "created_at"),
)

# -- Group C: obligation operational core -----------------------------------
#
# A deliberately reduced form of the full §9.4 design for this pass: the
# many-to-many `proposal_obligations` join table and the standalone
# `proposal_executions` table are folded into `proposed_actions` as extra
# columns (`obligation_ids`/`patient_ids` as JSONB, `exec_*` flattened
# alongside `prov_*`/`dec_*`), because this vertical slice never produces a
# proposal spanning more than one obligation and delivery-status callbacks
# (the reason `proposal_executions` was its own table) are Phase 17/18
# (WhatsApp inbound), explicitly deferred. `incoming_messages` is omitted
# for the same reason. Nothing here blocks adding either table later — no
# other table references them.

responsible_parties = Table(
    "responsible_parties",
    metadata,
    Column("party_id", String, primary_key=True),
    Column("display_name", String, nullable=False),
    Column(
        "role",
        String,
        CheckConstraint("role IN ('SITE_COORDINATOR','INVESTIGATOR','LAB','CLINICIAN')", name="ck_party_role"),
        nullable=False,
    ),
    Column("site_id", String, nullable=True),
    Column("email", String, nullable=True),
    Column("phone", String, nullable=True),
    Column("preferred_channel", String, nullable=False, server_default="IN_APP"),
    # Reduced form: trial_ids as JSONB rather than a `party_trials` join
    # table — the registry is small (seeded from one fixture) and filtered
    # in Python, never queried with a SQL join.
    Column("trial_ids", JSONB, nullable=False, server_default="[]"),
)

obligations = Table(
    "obligations",
    metadata,
    Column("obligation_id", String, primary_key=True),
    Column("obligation_key", String, nullable=False),
    Column("trial_id", String, ForeignKey("trials.trial_id"), nullable=False),
    Column("patient_id", String, nullable=False),
    Column("type", String, nullable=False),
    Column(
        "status",
        String,
        CheckConstraint(
            "status IN ('OPEN','AWAITING_RESPONSE','RESOLVED','DISMISSED')", name="ck_obligation_status"
        ),
        nullable=False,
    ),
    Column(
        "priority",
        String,
        CheckConstraint("priority IN ('LOW','MEDIUM','HIGH','URGENT')", name="ck_obligation_priority"),
        nullable=False,
    ),
    Column("requirement_ref", String, nullable=False),
    Column("requirement_text", String, nullable=False),
    Column("protocol_id", String, nullable=False),
    Column("source_ref", String, nullable=False),
    Column("detector_source", String, nullable=False),
    Column("occurrence", String, nullable=False, server_default=""),
    Column("title", String, nullable=False),
    Column("detail", String, nullable=False),
    Column("evidence", JSONB, nullable=False, server_default="[]"),
    Column("first_detected_at", DateTime(timezone=True), nullable=False),
    Column("last_confirmed_at", DateTime(timezone=True), nullable=False),
    Column("due_at", DateTime(timezone=True), nullable=True),
    Column("responsible_party_id", String, ForeignKey("responsible_parties.party_id"), nullable=True),
    Column("escalation_count", Integer, nullable=False, server_default="0"),
    Column("action_count", Integer, nullable=False, server_default="0"),
    Column("last_action_at", DateTime(timezone=True), nullable=True),
    Column("resolved_at", DateTime(timezone=True), nullable=True),
    Column(
        "resolution_kind",
        String,
        CheckConstraint(
            "resolution_kind IN ('SATISFIED','DISMISSED','SUPERSEDED') OR resolution_kind IS NULL",
            name="ck_obligation_resolution_kind",
        ),
        nullable=True,
    ),
    Column("resolution_by", String, nullable=True),
    Column("resolution_note", String, nullable=True),
    Column("resolution_at", DateTime(timezone=True), nullable=True),
    CheckConstraint(
        "(status IN ('OPEN','AWAITING_RESPONSE') AND resolved_at IS NULL AND resolution_kind IS NULL) "
        "OR (status IN ('RESOLVED','DISMISSED') AND resolved_at IS NOT NULL AND resolution_kind IS NOT NULL "
        "AND resolution_by IS NOT NULL AND resolution_note IS NOT NULL)",
        name="ck_obligation_terminal_has_resolution",
    ),
    Index("obligations_queue", "trial_id", "status", "priority", "first_detected_at"),
    Index("obligations_scope", "trial_id", "patient_id", "detector_source"),
    Index("obligations_party", "responsible_party_id"),
)

# The partial unique index needs a real SQL predicate on the *column*, not a
# free-standing `String(...)` — expressed properly via the table's own
# column object, added here rather than in the Table(...) call above so the
# predicate can reference `obligations.c.status` after the table exists.
Index(
    "obligations_active_key",
    obligations.c.obligation_key,
    unique=True,
    postgresql_where=obligations.c.status.in_(["OPEN", "AWAITING_RESPONSE"]),
)

obligation_actions = Table(
    "obligation_actions",
    metadata,
    Column("action_id", String, primary_key=True),
    Column("obligation_id", String, ForeignKey("obligations.obligation_id"), nullable=False),
    Column("seq", Integer, CheckConstraint("seq >= 1", name="ck_action_seq_positive"), nullable=False),
    Column("kind", String, nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column(
        "actor_kind",
        String,
        CheckConstraint("actor_kind IN ('SYSTEM','AGENT','RESEARCHER')", name="ck_action_actor_kind"),
        nullable=False,
    ),
    Column("actor_name", String, nullable=True),
    Column("channel", String, nullable=True),
    Column("recipient_party_id", String, ForeignKey("responsible_parties.party_id"), nullable=True),
    Column("ref_id", String, nullable=True),
    Column("note", String, nullable=False, server_default=""),
    Column("payload", JSONB, nullable=False, server_default="{}"),
    UniqueConstraint("obligation_id", "seq", name="ledger_order"),
    CheckConstraint(
        "(actor_kind = 'RESEARCHER' AND actor_name IS NOT NULL AND actor_name <> '') "
        "OR (actor_kind <> 'RESEARCHER' AND actor_name IS NULL)",
        name="researcher_is_named",
    ),
    Index("ix_obligation_actions_obligation_seq", "obligation_id", "seq"),
)

proposed_actions = Table(
    "proposed_actions",
    metadata,
    Column("proposal_id", String, primary_key=True),
    Column("obligation_ids", JSONB, nullable=False),
    Column("trial_id", String, ForeignKey("trials.trial_id"), nullable=False),
    Column("patient_ids", JSONB, nullable=False),
    Column("action_type", String, nullable=False),
    Column(
        "status",
        String,
        CheckConstraint(
            "status IN ('DRAFT','APPROVED','REJECTED','EXECUTED','FAILED')", name="ck_proposal_status"
        ),
        nullable=False,
    ),
    Column("recipient_party_id", String, nullable=False),
    Column("channel", String, nullable=False),
    Column("subject", String, nullable=False),
    Column("body", String, nullable=False),
    Column("reason", String, nullable=False),
    Column("evidence", JSONB, nullable=False, server_default="[]"),
    Column("template_name", String, nullable=True),
    Column("template_params", JSONB, nullable=False, server_default="[]"),
    Column("created_at", DateTime(timezone=True), nullable=False),
    # provenance, flattened — queried directly ("show me every degraded draft")
    Column("prov_generated_by", String, nullable=False),
    Column(
        "prov_provider_kind",
        String,
        CheckConstraint("prov_provider_kind IN ('TEMPLATE','LOCAL','HOSTED')", name="ck_prov_provider_kind"),
        nullable=False,
    ),
    Column("prov_model_name", String, nullable=True),
    Column("prov_prompt_version", String, nullable=True),
    Column("prov_latency_ms", Integer, nullable=True),
    Column("prov_degraded", Boolean, nullable=False, server_default="false"),
    Column("prov_tools_called", JSONB, nullable=False, server_default="[]"),
    Column("prov_evidence_ids", JSONB, nullable=False, server_default="[]"),
    Column("prov_unresolved", JSONB, nullable=False, server_default="[]"),
    # decision, flattened; NULL until a human decides
    Column("dec_outcome", String, nullable=True),
    Column("dec_reviewer", String, nullable=True),
    Column("dec_note", String, nullable=True),
    Column("dec_decided_at", DateTime(timezone=True), nullable=True),
    Column("dec_edited_subject", String, nullable=True),
    Column("dec_edited_body", String, nullable=True),
    # execution, flattened (folded from the standalone `proposal_executions`
    # table — see the module-level note above)
    Column("exec_executed_at", DateTime(timezone=True), nullable=True),
    Column("exec_provider", String, nullable=True),
    Column("exec_channel", String, nullable=True),
    Column("exec_notification_id", String, nullable=True),
    Column("exec_provider_message_id", String, nullable=True),
    Column("exec_provider_thread_id", String, nullable=True),
    Column("exec_delivery_status", String, nullable=True),
    Column("exec_error", String, nullable=True),
    Index("ix_proposed_actions_status_created", "status", "created_at"),
    Index("ix_proposed_actions_recipient", "recipient_party_id"),
)

approval_records = Table(
    "approval_records",
    metadata,
    Column("proposal_id", String, ForeignKey("proposed_actions.proposal_id"), primary_key=True),
    Column("approved_by", String, CheckConstraint("approved_by <> ''", name="ck_approved_by_nonempty"), nullable=False),
    Column("approved_at", DateTime(timezone=True), nullable=False),
    Column("channel", String, nullable=False),
    Column("subject", String, nullable=False),
    Column("body", String, nullable=False),
    Column("template_name", String, nullable=True),
    Column("template_params", JSONB, nullable=False, server_default="[]"),
)
