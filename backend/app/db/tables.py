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
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    MetaData,
    String,
    Table,
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
    Index("ix_notifications_patient_created", "patient_id", "created_at"),
)
