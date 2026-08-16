"""Observation ingestion.

Validates at the boundary, then persists the whole batch in a single write.

Two properties matter here:

  * **Nothing is silently dropped.** An invalid row is refused *and reported*,
    with the reason, so a caller can see that a sensor is misconfigured rather
    than wondering why its data never appeared.
  * **Nothing is silently corrected.** A wrong unit is refused, never converted.
    Phase 1 refuses to convert mmol/mol to %; the same rule applies to a heart
    rate arriving in the wrong unit.

Batch-only by construction: `MonitoringRepository.save_observations` takes a
list, so a thousand-row upload is one store write rather than a thousand.
"""

from __future__ import annotations

from datetime import datetime

from . import ids, quality
from ..repository.monitoring_base import MonitoringRepository
from ..schema.monitoring import Observation
from ..schema.monitoring_enums import MonitoringEventType
from ..schema.monitoring_result import (
    IngestionResult,
    MonitoringEvent,
    RejectedObservation,
)


class ObservationIngestionService:
    def __init__(self, monitoring_repository: MonitoringRepository) -> None:
        self.monitoring_repository = monitoring_repository

    def ingest(
        self, observations: list[Observation], now: datetime
    ) -> IngestionResult:
        accepted: list[Observation] = []
        rejected: list[RejectedObservation] = []

        for observation in observations:
            reason = quality.check_observation(observation)
            if reason is None:
                accepted.append(observation)
            else:
                rejected.append(
                    RejectedObservation(observation=observation, reason=reason)
                )

        # One write for the whole batch.
        self.monitoring_repository.save_observations(accepted)

        patient_ids = sorted({o.patient_id for o in accepted})
        if accepted:
            self.monitoring_repository.append_events(
                [
                    self._event(patient_id, accepted, rejected, now)
                    for patient_id in patient_ids
                ]
            )

        return IngestionResult(
            accepted_count=len(accepted),
            rejected=rejected,
            patient_ids=patient_ids,
        )

    @staticmethod
    def _event(
        patient_id: str,
        accepted: list[Observation],
        rejected: list[RejectedObservation],
        now: datetime,
    ) -> MonitoringEvent:
        mine = [o for o in accepted if o.patient_id == patient_id]
        mine_rejected = [r for r in rejected if r.observation.patient_id == patient_id]
        types = sorted({o.measurement_type.value for o in mine})

        summary = f"Ingested {len(mine)} observation(s): {', '.join(types)}."
        if mine_rejected:
            summary += f" {len(mine_rejected)} rejected as invalid."

        return MonitoringEvent(
            event_id=ids.new_id(ids.EVENT),
            patient_id=patient_id,
            trial_id=mine[0].trial_id,
            occurred_at=now,
            event_type=MonitoringEventType.OBSERVATIONS_INGESTED,
            summary=summary,
            payload={
                "accepted": len(mine),
                "rejected": len(mine_rejected),
                "measurement_types": types,
            },
        )
