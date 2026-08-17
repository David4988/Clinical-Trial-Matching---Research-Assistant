from datetime import datetime, timezone
import pytest

from app.risk.synthetic_provider import SyntheticArtifactProvider
from app.schema.monitoring_enums import RiskLevel, MeasurementType
from app.schema.monitoring_result import PatientState

def test_synthetic_provider_loads_and_maps():
    provider = SyntheticArtifactProvider()
    
    # Fake state for SUDDEN_DETERIORATION
    state = PatientState(
        patient_id="PT-demo-SUDDEN_DETERIORATION",
        trial_id="CT-123",
        measurements=[],
        active_treatments=[],
        recent_events=[],
        data_quality_issues=[],
        as_of=datetime(2026, 8, 16, tzinfo=timezone.utc)
    )
    
    risk = provider.assess(state, state.as_of)
    
    assert risk.provider == "synthetic"
    assert risk.model_version == "isolation_forest_c0.10"
    
    # We expect high risk for SUDDEN_DETERIORATION in the synthetic data
    assert risk.level == RiskLevel.RED
    
    # Should have some likely patterns
    assert len(risk.likely_patterns) > 0
    
    # Check provenance
    assert any("[Source: synthetic" in p for p in risk.likely_patterns)

def test_synthetic_provider_default_stable():
    provider = SyntheticArtifactProvider()
    
    state = PatientState(
        patient_id="PT-demo-STABLE",
        trial_id="CT-123",
        measurements=[],
        active_treatments=[],
        recent_events=[],
        data_quality_issues=[],
        as_of=datetime(2026, 8, 16, tzinfo=timezone.utc)
    )
    
    risk = provider.assess(state, state.as_of)
    assert risk.level == RiskLevel.GREEN

def test_synthetic_provider_missing_case_degrades():
    provider = SyntheticArtifactProvider()
    
    state = PatientState(
        patient_id="PT-demo-UNKNOWN_SCENARIO",
        trial_id="CT-123",
        measurements=[],
        active_treatments=[],
        recent_events=[],
        data_quality_issues=[],
        as_of=datetime(2026, 8, 16, tzinfo=timezone.utc)
    )
    
    risk = provider.assess(state, state.as_of)
    assert risk.degraded is True
    assert risk.level == RiskLevel.UNKNOWN
