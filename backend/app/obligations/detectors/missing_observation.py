"""Missing-required-observation detector — the second detector,
`docs/FINAL_IMPLEMENTATION_PLAN.md` §5.9/§26 Phase 5.

Reuses the monitoring layer's own truth: a `MonitoringCycleResult` already
carries `state.data_quality.flags`, computed deterministically by
`monitoring/quality.py` against `protocol.REQUIRED_MEASUREMENTS`. This
detector adds no new truth — it reads a `DataQualityCode.MISSING_MEASUREMENT`
flag exactly as it already exists and turns it into a `DetectedRequirement`,
the same narrow translation `detectors/missing_lab.py` does for a `CriterionResult`.
"""

from __future__ import annotations

from ...schema.clinical import Evidence
from ...schema.enums import EvidenceSource
from ...schema.monitoring_enums import DataQualityCode
from ...schema.monitoring_result import MonitoringCycleResult
from ...schema.obligation_enums import DetectorSource, ObligationType
from ...schema.obligations import DetectedRequirement


def detect(cycle: MonitoringCycleResult) -> list[DetectedRequirement]:
    """Pure. Reads only the snapshot embedded in `cycle` — never today's
    live patient state — so a later cycle with the observation present is
    what changes the answer, matching `missing_lab.detect`'s same contract."""

    detected: list[DetectedRequirement] = []
    for flag in cycle.state.data_quality.flags:
        if flag.code is not DataQualityCode.MISSING_MEASUREMENT:
            continue
        for measurement_type in flag.measurement_types:
            requirement_ref = measurement_type.value
            detected.append(
                DetectedRequirement(
                    type=ObligationType.MISSING_REQUIRED_OBSERVATION,
                    trial_id=cycle.trial_id,
                    patient_id=cycle.patient_id,
                    requirement_ref=requirement_ref,
                    requirement_text=(
                        f"{requirement_ref.replace('_', ' ').title()} observation "
                        "required by the monitoring protocol"
                    ),
                    protocol_id=cycle.trial_id,
                    source_ref=cycle.cycle_id,
                    evidence=[
                        Evidence(
                            source_type=EvidenceSource.OBSERVATION,
                            locator=requirement_ref,
                            snippet=flag.message,
                            note=None,
                        )
                    ],
                )
            )
    return detected


SOURCE = DetectorSource.MONITORING_OBSERVATION
