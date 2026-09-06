"""The second detector: `MISSING_REQUIRED_OBSERVATION`, sourced from
`MonitoringCycleResult.state.data_quality.flags` — the existing monitoring
truth, not a new one. `docs/FINAL_IMPLEMENTATION_PLAN.md` §26 Phase 5.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.obligations.detectors import missing_observation
from app.obligations.service import ObligationService
from app.repository.json_obligations import JsonObligationRepository
from app.schema.enums import Severity
from app.schema.monitoring_enums import DataQualityCode, MeasurementType, RiskLevel
from app.schema.monitoring_result import (
    DataQuality,
    DataQualityFlag,
    EffectiveRisk,
    MonitoringCycleResult,
    PatientState,
    RiskAssessment,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _cycle(missing: list[MeasurementType]) -> MonitoringCycleResult:
    state = PatientState(
        patient_id="P-3311",
        trial_id="CT-001",
        as_of=NOW,
        data_quality=DataQuality(
            flags=(
                [
                    DataQualityFlag(
                        code=DataQualityCode.MISSING_MEASUREMENT,
                        severity=Severity.WARN,
                        message="The protocol requires " + ", ".join(m.value for m in missing) + "; no reading is recorded.",
                        measurement_types=missing,
                    )
                ]
                if missing
                else []
            )
        ),
    )
    return MonitoringCycleResult(
        cycle_id="CY-1",
        patient_id="P-3311",
        trial_id="CT-001",
        generated_at=NOW,
        state=state,
        risk=RiskAssessment(
            assessment_id="RA-1", patient_id="P-3311", trial_id="CT-001", assessed_at=NOW,
            level=RiskLevel.GREEN, score=0.1, confidence=0.9, prediction_horizon_hours=24,
            provider="mock", model_version="v1",
        ),
        effective_risk=EffectiveRisk(level=RiskLevel.GREEN, provider_level=RiskLevel.GREEN),
    )


def test_detects_missing_required_observation():
    cycle = _cycle([MeasurementType.HEART_RATE])
    detected = missing_observation.detect(cycle)
    assert len(detected) == 1
    req = detected[0]
    assert req.type.value == "MISSING_REQUIRED_OBSERVATION"
    assert req.requirement_ref == "HEART_RATE"
    assert req.patient_id == "P-3311"
    assert req.trial_id == "CT-001"


def test_no_gap_produces_nothing():
    assert missing_observation.detect(_cycle([])) == []


def test_multiple_missing_measurements_produce_multiple_requirements():
    detected = missing_observation.detect(_cycle([MeasurementType.HEART_RATE, MeasurementType.SPO2]))
    assert {r.requirement_ref for r in detected} == {"HEART_RATE", "SPO2"}


def test_service_dedups_across_repeated_cycles(tmp_path):
    repo = JsonObligationRepository(tmp_path / "obligations.json")
    service = ObligationService(repo)

    service.detect_from_monitoring_cycle(_cycle([MeasurementType.HEART_RATE]), now=NOW)
    service.detect_from_monitoring_cycle(_cycle([MeasurementType.HEART_RATE]), now=NOW)

    obligations = repo.list_obligations(trial_id="CT-001", patient_id="P-3311")
    assert len(obligations) == 1
    assert obligations[0].detector_source == "MONITORING_OBSERVATION"
    assert obligations[0].obligation_key == "CT-001|P-3311|MISSING_REQUIRED_OBSERVATION|HEART_RATE|"


def test_service_auto_resolves_when_observation_arrives(tmp_path):
    repo = JsonObligationRepository(tmp_path / "obligations.json")
    service = ObligationService(repo)

    service.detect_from_monitoring_cycle(_cycle([MeasurementType.HEART_RATE]), now=NOW)
    service.detect_from_monitoring_cycle(_cycle([]), now=NOW)  # the next cycle has the reading

    obligations = repo.list_obligations(trial_id="CT-001", patient_id="P-3311")
    assert len(obligations) == 1
    assert obligations[0].status.value == "RESOLVED"


def test_screening_and_monitoring_scopes_are_independent(tmp_path):
    # A SCREENING-sourced obligation must never be touched or resolved by a
    # MONITORING_OBSERVATION reconciliation pass over the same patient/trial
    # — the DetectionScope guard (§6.4) applies per source, not just per
    # (trial, patient).
    from app.obligations import reconcile as reconcile_module
    from app.schema.obligation_enums import ObligationType
    from app.schema.obligations import DetectedRequirement

    repo = JsonObligationRepository(tmp_path / "obligations.json")
    service = ObligationService(repo)

    screening_delta = reconcile_module.reconcile(
        trial_id="CT-001", patient_id="P-3311", detector_source="SCREENING",
        detected=[
            DetectedRequirement(
                type=ObligationType.MISSING_LAB_EVIDENCE, trial_id="CT-001", patient_id="P-3311",
                requirement_ref="INC-04", requirement_text="eGFR", protocol_id="CT-001", source_ref="SR-1",
            )
        ],
        existing=[], now=NOW,
    )
    service._persist(screening_delta)  # noqa: SLF001 - test-only, mirrors service internals

    service.detect_from_monitoring_cycle(_cycle([MeasurementType.HEART_RATE]), now=NOW)

    obligations = repo.list_obligations(trial_id="CT-001", patient_id="P-3311")
    assert len(obligations) == 2
    assert {o.detector_source for o in obligations} == {"SCREENING", "MONITORING_OBSERVATION"}
    assert all(o.status.value == "OPEN" for o in obligations)
