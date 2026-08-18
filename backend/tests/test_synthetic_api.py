from fastapi.testclient import TestClient

from app.main import app, create_app
from app.monitoring.context import MonitoringContext
from app.repository.json_monitoring import JsonMonitoringRepository
from app.repository.json_repo import JsonRepository
from app.risk.factory import build_risk_provider
from app.service import ScreeningService

client = TestClient(app)


def _isolated_app(tmp_path, risk_provider="synthetic_ml"):
    """The whole stack over throwaway stores, so seeding cannot collide."""
    service = ScreeningService(repository=JsonRepository(tmp_path / "store.json"))
    return create_app(
        service=service,
        monitoring=MonitoringContext.build(
            service.repository,
            monitoring_repository=JsonMonitoringRepository(
                tmp_path / "monitoring.json"
            ),
            risk_provider=build_risk_provider(risk_provider),
        ),
    )

def test_seed_demo_default():
    # Default uses the deterministic mock provider
    response = client.post(
        "/monitoring/demo/seed",
        json={"trial_id": "CT-001"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["synthetic"] is True
    # The default provider shouldn't raise errors

def test_seed_demo_with_synthetic_ml():
    # True uses the new SyntheticArtifactProvider
    response = client.post(
        "/monitoring/demo/seed",
        json={"trial_id": "CT-001", "use_synthetic_ml": True}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["synthetic"] is True
    assert "patients" in data


# -- the three-provider split ----------------------------------------------


def test_use_synthetic_ml_still_means_the_static_fixture_provider(tmp_path):
    """The old flag predates `synthetic_ml` and must keep its old meaning."""
    response = TestClient(_isolated_app(tmp_path, "mock")).post(
        "/monitoring/demo/seed",
        json={"trial_id": "CT-COMPAT", "use_synthetic_ml": True, "windows": 2},
    )
    assert response.status_code == 200
    assert response.json()["risk_provider"] == "synthetic"


def test_seed_demo_can_run_the_live_model(tmp_path):
    # Isolated: seeding is idempotent per patient, so a persistent store would
    # make this pass or fail depending on what ran before it.
    response = TestClient(_isolated_app(tmp_path)).post(
        "/monitoring/demo/seed",
        json={"trial_id": "CT-LIVE-ML", "risk_provider": "synthetic_ml", "windows": 3},
    )
    assert response.status_code == 200
    data = response.json()

    assert data["risk_provider"] == "synthetic_ml"
    assert data["model_version"] == "synthetic_if_v1"

    # The cohort spans stable and deteriorating trajectories, so a live model
    # scoring real windows must not answer identically for all of them.
    progressions = [
        tuple(p["risk_progression"]) for p in data["patients"] if "risk_progression" in p
    ]
    assert progressions
    assert len(set(progressions)) > 1


def test_seeded_cycles_record_the_live_model_as_their_source(tmp_path):
    # Isolated stores: the shared demo cohort reuses patient ids across trials,
    # and cycles are keyed by patient, so a shared store cannot answer "which
    # provider produced this patient's latest cycle".
    isolated = TestClient(_isolated_app(tmp_path))
    isolated.post(
        "/monitoring/demo/seed",
        json={"trial_id": "CT-PROV", "risk_provider": "synthetic_ml", "windows": 3},
    )
    cycle = isolated.get("/monitoring/patients/P-2004/cycle").json()

    assert cycle["risk"]["provider"] == "synthetic_ml"
    assert cycle["risk"]["model_version"] == "synthetic_if_v1"
    # The contributing factors name the estimator that produced the verdict.
    assert any(
        f["factor"] == "ISOLATION_FOREST" for f in cycle["risk"]["contributing_factors"]
    ) or cycle["risk"]["degraded"]


# -- model provenance endpoint ---------------------------------------------


def test_model_endpoint_reports_the_running_provider():
    payload = client.get("/monitoring/model").json()

    assert payload["provider"] in {"mock-risk-v1", "synthetic", "synthetic_ml"}
    assert "model_version" in payload
    assert isinstance(payload["live_inference"], bool)


def test_model_endpoint_exposes_the_artifact_when_live(tmp_path):
    payload = TestClient(_isolated_app(tmp_path)).get("/monitoring/model").json()

    assert payload["provider"] == "synthetic_ml"
    assert payload["live_inference"] is True

    artifact = payload["artifact"]
    assert artifact["features"] == [
        "heart_rate",
        "spo2",
        "respiratory_rate",
        "heart_rate_delta",
        "spo2_delta",
        "respiratory_rate_delta",
    ]
    assert artifact["estimator"]["contamination"] == 0.10
    assert artifact["estimator"]["random_state"] == 42
    assert sorted(artifact["training_cohort"]["scenarios"]) == ["IMPROVING", "STABLE"]
    assert len(artifact["model_sha256"]) == 64


def test_artifact_provenance_offers_a_scalar_for_every_nested_field(tmp_path):
    """The badge renders leaves, never the nested objects themselves.

    `estimator`, `training_cohort` and `scoring` are objects copied straight
    out of the artifact's metadata. The monitoring badge reads one scalar from
    each; pinning those here means a metadata rename shows up as a failing test
    rather than as a silently empty row on the provenance panel.
    """
    artifact = (
        TestClient(_isolated_app(tmp_path)).get("/monitoring/model").json()["artifact"]
    )

    assert isinstance(artifact["estimator"]["class"], str)
    assert isinstance(artifact["training_cohort"]["source"], str)
    assert isinstance(artifact["training_cohort"]["total_patients"], int)
    assert isinstance(artifact["training_cohort"]["fitted_rows"], int)
    assert isinstance(artifact["scoring"]["anomaly_score"], str)
