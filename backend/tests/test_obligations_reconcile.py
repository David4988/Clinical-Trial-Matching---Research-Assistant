"""`obligations/reconcile.py` — the pure CREATE/TOUCH/AUTO-RESOLVE function.
Tested with plain Python objects, no fixtures, no I/O, matching the plan's
own stated intent for this file (§6.4)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.obligations import reconcile as reconcile_module
from app.schema.obligation_enums import ObligationStatus
from app.schema.obligations import DetectedRequirement

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _req(ref="INC-04") -> DetectedRequirement:
    return DetectedRequirement(
        type="MISSING_LAB_EVIDENCE",
        trial_id="CT-001",
        patient_id="P-3311",
        requirement_ref=ref,
        requirement_text="eGFR at least 45 mL/min",
        protocol_id="CT-001",
        source_ref="SR-1",
        evidence=[],
    )


def test_create_on_first_detection():
    delta = reconcile_module.reconcile(
        trial_id="CT-001", patient_id="P-3311", detector_source="SCREENING",
        detected=[_req()], existing=[], now=NOW,
    )
    assert len(delta.created) == 1
    assert len(delta.touched) == 0
    assert len(delta.auto_resolved) == 0
    obligation = delta.created[0]
    assert obligation.status is ObligationStatus.OPEN
    assert obligation.first_detected_at == obligation.last_confirmed_at == NOW
    assert obligation.action_count == 1
    assert [a.kind.value for a in delta.created_actions] == ["DETECTED"]


def test_touch_preserves_identity_fields_and_never_reopens_first_detected_at():
    first = reconcile_module.reconcile(
        trial_id="CT-001", patient_id="P-3311", detector_source="SCREENING",
        detected=[_req()], existing=[], now=NOW,
    ).created[0]

    later = NOW + timedelta(days=3)
    second = reconcile_module.reconcile(
        trial_id="CT-001", patient_id="P-3311", detector_source="SCREENING",
        detected=[_req()], existing=[first], now=later,
    )
    assert len(second.created) == 0
    assert len(second.touched) == 1
    touched = second.touched[0]

    # never changed on touch
    assert touched.obligation_id == first.obligation_id
    assert touched.obligation_key == first.obligation_key
    assert touched.first_detected_at == first.first_detected_at
    assert touched.status == first.status
    assert touched.escalation_count == first.escalation_count
    assert touched.resolved_at is None

    # advanced
    assert touched.last_confirmed_at == later


def test_auto_resolve_when_detector_stops_reporting_the_key():
    first = reconcile_module.reconcile(
        trial_id="CT-001", patient_id="P-3311", detector_source="SCREENING",
        detected=[_req()], existing=[], now=NOW,
    ).created[0]

    later = NOW + timedelta(days=1)
    result = reconcile_module.reconcile(
        trial_id="CT-001", patient_id="P-3311", detector_source="SCREENING",
        detected=[], existing=[first], now=later,
    )
    assert len(result.auto_resolved) == 1
    resolved = result.auto_resolved[0]
    assert resolved.status is ObligationStatus.RESOLVED
    assert resolved.resolution.kind.value == "SATISFIED"
    assert resolved.resolution.by == "SYSTEM"
    assert resolved.resolved_at == later


def test_reconfirmed_ledger_entry_is_throttled():
    first = reconcile_module.reconcile(
        trial_id="CT-001", patient_id="P-3311", detector_source="SCREENING",
        detected=[_req()], existing=[], now=NOW,
    ).created[0]

    soon = NOW + timedelta(minutes=5)
    soon_delta = reconcile_module.reconcile(
        trial_id="CT-001", patient_id="P-3311", detector_source="SCREENING",
        detected=[_req()], existing=[first], now=soon,
    )
    assert soon_delta.touched_actions == []  # throttled: too soon since last_action_at

    much_later = NOW + timedelta(hours=7)
    later_delta = reconcile_module.reconcile(
        trial_id="CT-001", patient_id="P-3311", detector_source="SCREENING",
        detected=[_req()], existing=[first], now=much_later,
    )
    assert [a.kind.value for a in later_delta.touched_actions] == ["RECONFIRMED"]


def test_obligation_key_is_pure_string_composition():
    from app.obligations.rules import obligation_key
    from app.schema.obligation_enums import ObligationType

    key = obligation_key("CT-001", "P-3311", ObligationType.MISSING_LAB_EVIDENCE, "INC-04")
    assert key == "CT-001|P-3311|MISSING_LAB_EVIDENCE|INC-04|"
