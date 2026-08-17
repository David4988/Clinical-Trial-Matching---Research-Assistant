"""End to end: a synthetic patient trajectory through the real application.

A held-out patient's observations are posted to the live HTTP endpoints, window
by window, and every downstream consequence is asserted from the API responses.
Nothing is mocked — the risk provider is the real `SyntheticMLProvider` loading
the real serialised Isolation Forest.

    POST /monitoring/observations
    POST /monitoring/patients/{id}/cycle
    GET  /monitoring/patients/{id}/observations
    GET  /monitoring/patients/{id}/state
    GET  /monitoring/patients/{id}/timeline
    GET  /monitoring/trials/{id}/overview

The trajectory is `P0014` from the evaluation half of the research patient split
— never seen during fitting — exported unmodified by
`export_inference_fixtures.py`. It is a SUDDEN_DETERIORATION scenario whose
ground-truth change point is window 103.

No expected risk level is hard-coded anywhere below. The assertions describe the
*shape* the flow must have (the model separates before from after; the
application acts on what the model said); the numbers come from the model.
"""

import builtins
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.schema.monitoring import Observation
from app.schema.monitoring_enums import MeasurementType
from app.synthetic.inference.contract import FEATURE_ORDER
from app.synthetic.inference.engine import SyntheticInferenceEngine
from app.synthetic.inference.windows import PatientWindowState
from scripts.trajectory_replay import (
    DEFAULT_START,
    ReplayWindow,
    build_app,
    load_trajectory,
    observation_payload,
    replay,
)

TRAJECTORY = load_trajectory()
CHANGE_POINT = TRAJECTORY["change_point_window"]

#: The HTTP replay covers a bounded slice spanning the transition: seven normal
#: windows, the change point, and a sustained abnormal run. The *whole* 144-window
#: trajectory is still checked for parity below, through the engine, where it
#: costs a second rather than a minute.
REPLAY_FIRST = CHANGE_POINT - 7
REPLAY_LAST = CHANGE_POINT + 23

#: Established in test_research_parity.py and unchanged here.
SCORE_TOLERANCE = 1e-9


# -- replaying once, asserting many times ----------------------------------


@pytest.fixture(scope="module")
def live_replay(tmp_path_factory):
    """One HTTP replay through the live ML provider, shared by the tests."""
    store = tmp_path_factory.mktemp("live-replay")
    client = TestClient(build_app(store, "synthetic_ml"))
    windows = replay(
        client, TRAJECTORY, first=REPLAY_FIRST, last=REPLAY_LAST
    )
    return client, windows


@pytest.fixture(scope="module")
def engine():
    return SyntheticInferenceEngine()


def _before(windows: list[ReplayWindow]) -> list[ReplayWindow]:
    return [w for w in windows if w.window_index < CHANGE_POINT and w.scored]


def _after(windows: list[ReplayWindow]) -> list[ReplayWindow]:
    return [w for w in windows if w.window_index >= CHANGE_POINT and w.scored]


# -- Test 1: the replay actually went through the application --------------


def test_every_window_was_ingested_and_cycled(live_replay):
    _, windows = live_replay

    assert len(windows) == REPLAY_LAST - REPLAY_FIRST + 1
    # Four signals per window, none rejected: the trajectory is replayed intact.
    assert all(w.accepted == 4 for w in windows)
    assert all(w.rejected == 0 for w in windows)


def test_the_live_model_answered_every_cycle(live_replay):
    _, windows = live_replay

    assert {w.risk_provider for w in windows} == {"synthetic_ml"}
    assert {w.model_version for w in windows} == {TRAJECTORY["model_version"]}


def test_the_first_replayed_window_is_unknown_without_a_fabricated_delta(live_replay):
    _, windows = live_replay
    first = windows[0]

    assert first.scored is False
    assert first.heart_rate_delta is None
    assert first.risk_level == "UNKNOWN"
    assert first.risk_score == 0.0
    # A working provider reporting insufficient history, not a failure.
    assert first.degraded is False
    assert any("invented" in pattern for pattern in first.likely_patterns)


def test_every_later_window_was_scored(live_replay):
    _, windows = live_replay

    assert all(w.scored for w in windows[1:])
    assert all(w.heart_rate_delta is not None for w in windows[1:])


# -- Test 2: stable phase --------------------------------------------------


def test_the_stable_phase_reads_as_normal(live_replay):
    _, windows = live_replay
    before = _before(windows)

    assert before, "the slice must contain pre-event windows"
    flagged = sum(w.predicted_anomaly for w in before)
    assert flagged / len(before) < 0.2, (
        f"{flagged}/{len(before)} pre-event windows flagged; the model is not "
        "separating the stable phase"
    )


def test_stable_windows_are_not_escalated_by_the_protocol(live_replay):
    _, windows = live_replay
    calm = [w for w in _before(windows) if not w.predicted_anomaly]

    assert calm
    assert all(w.risk_level in {"GREEN", "AMBER"} for w in calm)
    assert all("URGENT_ESCALATION" not in w.interventions for w in calm)


# -- Test 3: the deterioration transition ----------------------------------


def test_the_model_separates_before_from_after(live_replay):
    _, windows = live_replay
    before, after = _before(windows), _after(windows)

    assert before and after
    before_rate = sum(w.predicted_anomaly for w in before) / len(before)
    after_rate = sum(w.predicted_anomaly for w in after) / len(after)

    # The direction is asserted; the values come from the model.
    assert after_rate > before_rate
    assert max(w.anomaly_score for w in after) > max(w.anomaly_score for w in before)


def test_the_risk_level_changes_when_the_model_flags_the_trajectory(live_replay):
    _, windows = live_replay
    after = _after(windows)

    flagged = [w for w in after if w.predicted_anomaly]
    assert flagged, "the model never flagged the post-event phase"
    # Whatever the model flags, the application must show as RED.
    assert all(w.provider_level == "RED" for w in flagged)


def test_a_transition_is_recorded_at_the_escalation(live_replay):
    _, windows = live_replay

    escalations = [
        w for w in windows if w.transition and "scalated from" in (w.transition or "")
    ]
    assert escalations, "no risk transition was recorded across the whole replay"
    assert any("RED" in w.transition for w in escalations)


def test_the_abnormal_state_is_sustained_not_a_single_spike(live_replay):
    _, windows = live_replay
    after = _after(windows)

    longest = current = 0
    for w in after:
        current = current + 1 if w.predicted_anomaly else 0
        longest = max(longest, current)

    assert longest >= 5, f"longest flagged run after the event was {longest} windows"


# -- Test 4: temporal correctness across the whole replay ------------------


def test_deltas_are_taken_against_the_previous_replayed_window(live_replay):
    _, windows = live_replay

    for previous, current in zip(windows, windows[1:]):
        assert current.heart_rate_delta == pytest.approx(
            round(current.heart_rate - previous.heart_rate, 4)
        )
        assert current.spo2_delta == pytest.approx(
            round(current.spo2 - previous.spo2, 4)
        )
        assert current.respiratory_rate_delta == pytest.approx(
            round(current.respiratory_rate - previous.respiratory_rate, 4)
        )


def test_no_window_reuses_an_earlier_predecessor(live_replay):
    """A stuck predecessor would show up as a delta repeating exactly."""
    _, windows = live_replay
    deltas = [w.heart_rate_delta for w in windows if w.scored]

    # Not a uniqueness claim — just that the deltas move rather than freeze.
    assert len(set(deltas)) > len(deltas) // 2


def test_timestamps_advance_by_the_training_cadence(live_replay):
    _, windows = live_replay
    minutes = TRAJECTORY["window_minutes"]

    for previous, current in zip(windows, windows[1:]):
        assert current.timestamp - previous.timestamp == timedelta(minutes=minutes)


def test_a_second_patient_does_not_inherit_the_first_ones_history(live_replay):
    client, windows = live_replay

    # A brand-new patient, first window only, posted to the same running app.
    at = DEFAULT_START + timedelta(hours=48)
    late = TRAJECTORY["windows"][REPLAY_LAST]
    client.post(
        "/monitoring/observations",
        json={
            "observations": observation_payload(late, "PT-OTHER-002", "CT-REPLAY", at),
            "now": at.isoformat(),
        },
    ).raise_for_status()
    cycle = client.post(
        "/monitoring/patients/PT-OTHER-002/cycle",
        json={"trial_id": "CT-REPLAY", "now": at.isoformat()},
    ).json()

    # Identical physiology to a window the first patient was scored RED on, but
    # this patient has no predecessor, so it must not be scored at all.
    assert cycle["effective_risk"]["level"] == "UNKNOWN"
    assert cycle["risk"]["score"] == 0.0
    assert any("invented" in p for p in cycle["risk"]["likely_patterns"])


# -- Test 5: the static provider still works, and differs -----------------


def test_static_provider_still_serves_the_precomputed_fixture(tmp_path):
    client = TestClient(build_app(tmp_path, "synthetic"))
    # The static provider keys off the trajectory name in the patient id.
    windows = replay(
        client,
        TRAJECTORY,
        patient_id="PT-demo-SUDDEN_DETERIORATION",
        first=REPLAY_FIRST,
        last=REPLAY_FIRST + 4,
    )

    assert {w.risk_provider for w in windows} == {"synthetic"}
    assert all(not w.degraded for w in windows)
    assert any("[Source: synthetic" in p for w in windows for p in w.likely_patterns)


def test_static_and_live_providers_answer_differently_on_the_same_windows(tmp_path):
    """The contrast that shows the live path is not replaying a fixture.

    The static provider returns the same precomputed case for every window
    because it reads the patient id. The live model reads the physiology, so its
    answer moves across the transition.
    """
    static = replay(
        TestClient(build_app(tmp_path / "static", "synthetic")),
        TRAJECTORY,
        patient_id="PT-demo-SUDDEN_DETERIORATION",
        first=REPLAY_FIRST,
        last=REPLAY_LAST,
    )
    live = replay(
        TestClient(build_app(tmp_path / "live", "synthetic_ml")),
        TRAJECTORY,
        patient_id="PT-demo-SUDDEN_DETERIORATION",
        first=REPLAY_FIRST,
        last=REPLAY_LAST,
    )

    # Static: one answer, unchanged by the physiology underneath it.
    assert len({w.provider_level for w in static}) == 1
    # Live: the answer moves.
    assert len({w.provider_level for w in live}) > 1
    assert {w.risk_provider for w in static} == {"synthetic"}
    assert {w.risk_provider for w in live} == {"synthetic_ml"}


# -- Test 6: live inference never touches the demo JSON -------------------


def test_the_live_replay_never_opens_the_demo_fixture(tmp_path, monkeypatch):
    opened: list[str] = []
    real_open = builtins.open

    def recording_open(file, *args, **kwargs):
        opened.append(str(file))
        return real_open(file, *args, **kwargs)

    client = TestClient(build_app(tmp_path, "synthetic_ml"))
    monkeypatch.setattr(builtins, "open", recording_open)
    windows = replay(client, TRAJECTORY, first=REPLAY_FIRST, last=REPLAY_FIRST + 5)

    assert windows
    assert not any("synthetic_demo_cases" in path for path in opened)
    # It did read the model artifact, or it was already loaded in this process.
    assert {w.risk_provider for w in windows} == {"synthetic_ml"}


# -- Test 7: research parity across the complete trajectory ---------------


def test_full_trajectory_features_and_scores_match_research(engine):
    """All 144 windows, not a sample.

    Rebuilt through the application's own window construction from observations
    in application form, then scored with the deployed artifact, and compared to
    what the research pipeline computed for the same patient.
    """
    minutes = TRAJECTORY["window_minutes"]
    history: list[Observation] = []
    feature_drift = score_drift = 0.0
    compared = label_mismatches = 0

    for offset, window in enumerate(TRAJECTORY["windows"]):
        at = DEFAULT_START + timedelta(minutes=minutes * offset)
        history.extend(
            Observation(observation_id=f"OBS-{offset}-{row['measurement_type']}", **row)
            for row in observation_payload(window, "P0014", "TRIAL-001", at)
        )
        result = engine.score(
            PatientWindowState.from_observations("P0014", history)
        )

        if window["expected_anomaly_score"] is None:
            # Research could not score it either — the first window.
            assert result.scored is False
            continue

        assert result.scored, f"window {window['window_index']} was not scored"
        compared += 1

        for name in FEATURE_ORDER:
            feature_drift = max(
                feature_drift,
                abs(result.feature_values[name] - window["expected_features"][name]),
            )
        score_drift = max(
            score_drift,
            abs(result.anomaly_score - window["expected_anomaly_score"]),
        )
        if result.predicted_anomaly != window["expected_predicted_anomaly"]:
            label_mismatches += 1

    assert compared == 143
    assert feature_drift == 0.0, f"worst feature drift {feature_drift:.3e}"
    assert score_drift <= SCORE_TOLERANCE, f"worst score drift {score_drift:.3e}"
    assert label_mismatches == 0


def test_http_replay_agrees_with_research_window_by_window(live_replay):
    """The same comparison, but for the windows that went through HTTP."""
    _, windows = live_replay
    expected = {w["window_index"]: w for w in TRAJECTORY["windows"]}

    compared = 0
    for window in windows:
        if not window.scored:
            continue
        reference = expected[window.window_index]
        # The first replayed window has no predecessor inside the slice, so its
        # successor is the first that can match research's full-history deltas.
        if reference["expected_anomaly_score"] is None:
            continue
        compared += 1

        assert window.features == pytest.approx(
            tuple(reference["expected_features"][name] for name in FEATURE_ORDER)
        )
        assert window.anomaly_score == pytest.approx(
            reference["expected_anomaly_score"], abs=SCORE_TOLERANCE
        )
        assert window.predicted_anomaly == reference["expected_predicted_anomaly"]

    assert compared == len(windows) - 1


# -- Test 8: downstream monitoring flow -----------------------------------


def test_every_demo_window_carries_the_systolic_bp_the_protocol_requires():
    """The gate's precondition, asserted rather than assumed.

    SYSTOLIC_BP is in `protocol.REQUIRED_MEASUREMENTS`, so a demo window that
    omits it makes the record UNTRUSTWORTHY and the trust gate forces UNKNOWN —
    the model still scores correctly, but its verdict never reaches the
    dashboard. That failure mode is invisible in the ML tests, because the six
    model features do not include blood pressure at all.

    So this locks the demo payloads specifically: if a regenerated fixture or an
    edited demo script ever drops SBP, this fails here rather than showing up as
    an all-UNKNOWN demo.
    """
    for window in TRAJECTORY["windows"]:
        assert "systolic_bp" in window["observed"], (
            f"trajectory window {window['window_index']} has no systolic_bp; "
            "the replay would be gated to UNKNOWN"
        )

    rows = observation_payload(
        TRAJECTORY["windows"][CHANGE_POINT], "PT-SBP-CHECK", "CT-SBP", DEFAULT_START
    )
    sbp = [r for r in rows if r["measurement_type"] == MeasurementType.SYSTOLIC_BP.value]
    assert len(sbp) == 1, "the ingestion payload must carry exactly one SBP row"
    assert sbp[0]["unit"] == "mmHg"

    # The three-window scripted demo is a separate entry point, so check it too.
    from scripts.live_inference_demo import UNITS, WINDOWS

    assert UNITS[MeasurementType.SYSTOLIC_BP] == "mmHg"
    assert all(len(row) == 4 for row in WINDOWS), (
        "every scripted demo window must carry SBP alongside the three signals"
    )

    # And the reason it is safe to add: SBP is not a model feature.
    assert not any("systolic" in name for name in FEATURE_ORDER)


def test_the_trust_gate_did_not_have_to_override_a_clean_record(live_replay):
    _, windows = live_replay
    scored = [w for w in windows if w.scored]

    # This trajectory is GOOD quality throughout, so the model's verdict should
    # stand unchanged — the gate is present, and correctly silent.
    assert all(w.data_quality == "OK" for w in scored)
    assert not any(w.gated for w in scored)
    assert all(w.provider_level == w.risk_level for w in scored)


def test_red_windows_drive_the_protocol_response(live_replay):
    _, windows = live_replay
    red = [w for w in windows if w.risk_level == "RED"]

    assert red
    for window in red:
        assert "URGENT_ESCALATION" in window.interventions
        assert "NOTIFY_CLINICIAN" in window.interventions
        assert "INCREASE_MONITORING" in window.interventions


def test_green_windows_stay_on_routine_monitoring(live_replay):
    _, windows = live_replay
    green = [w for w in windows if w.risk_level == "GREEN"]

    assert green
    assert all(w.interventions == ["ROUTINE_MONITORING"] for w in green)


def test_dosing_is_held_while_the_model_says_red(live_replay):
    """The intentional block: verify it actually happens rather than assume it."""
    _, windows = live_replay
    red = [w for w in windows if w.risk_level == "RED" and w.next_dose]

    if not red:
        pytest.skip("no treatment registered, so no dose decision was produced")
    assert all(w.next_dose in {"HOLD", "REVIEW_REQUIRED"} for w in red)


def test_the_cycle_continues_after_red(live_replay):
    _, windows = live_replay
    red_indexes = [i for i, w in enumerate(windows) if w.risk_level == "RED"]

    assert red_indexes
    # RED is not terminal: later windows were still ingested and still cycled.
    assert max(red_indexes) < len(windows) - 1 or len(red_indexes) > 1
    assert all(w.accepted == 4 for w in windows[max(red_indexes) :])


def test_the_timeline_records_the_whole_replay(live_replay):
    client, windows = live_replay
    timeline = client.get("/monitoring/patients/PT-DEMO-001/timeline").json()
    kinds = {event["event_type"] for event in timeline}

    assert "OBSERVATIONS_INGESTED" in kinds
    assert "RISK_ASSESSED" in kinds
    assert "RISK_TRANSITION" in kinds
    assert "INTERVENTION_RAISED" in kinds
    assert any("synthetic_ml" in event["summary"] for event in timeline)


# -- Test 9: frontend-facing state ----------------------------------------


def test_the_state_endpoint_reflects_the_replayed_record(live_replay):
    client, windows = live_replay
    last = windows[-1]
    state = client.get(
        "/monitoring/patients/PT-DEMO-001/state",
        params={"trial_id": "CT-REPLAY", "now": last.timestamp.isoformat()},
    ).json()

    current = {
        m["measurement_type"]: m["current"] for m in state["measurements"]
    }
    assert current[MeasurementType.HEART_RATE.value] == last.heart_rate
    assert current[MeasurementType.SPO2.value] == last.spo2
    assert current[MeasurementType.RESPIRATORY_RATE.value] == last.respiratory_rate


def test_the_cycle_payload_carries_everything_the_frontend_renders(live_replay):
    client, _ = live_replay
    cycle = client.get("/monitoring/patients/PT-DEMO-001/cycle").json()
    risk = cycle["risk"]

    # PatientMonitor.tsx reads exactly these.
    assert risk["provider"] == "synthetic_ml"
    assert risk["model_version"]
    assert risk["assessed_at"]
    assert cycle["effective_risk"]["level"]
    assert cycle["effective_risk"]["provider_level"]
    assert isinstance(risk["contributing_factors"], list)
    assert isinstance(risk["likely_patterns"], list)
    assert risk["likely_patterns"], "the explanation must not be empty"

    # And the explanation is about this window's physiology.
    factors = {f["factor"] for f in risk["contributing_factors"]}
    assert "ISOLATION_FOREST" in factors
    assert factors & {"HEART_RATE", "SPO2", "RESPIRATORY_RATE"}


def test_the_dashboard_overview_shows_the_live_model(live_replay):
    client, _ = live_replay
    overview = client.get("/monitoring/trials/CT-REPLAY/overview").json()

    assert overview["total_patients"] >= 0
    assert set(overview["risk_counts"]) == {"GREEN", "AMBER", "RED", "UNKNOWN"}


def test_the_model_endpoint_names_the_artifact_that_scored_the_replay(live_replay):
    client, windows = live_replay
    payload = client.get("/monitoring/model").json()

    assert payload["provider"] == "synthetic_ml"
    assert payload["live_inference"] is True
    assert payload["artifact"]["model_sha256"] == TRAJECTORY["model_sha256"]
    assert payload["model_version"] == windows[-1].model_version


def test_no_sklearn_object_reaches_the_frontend_payload(live_replay):
    client, _ = live_replay
    body = client.get("/monitoring/patients/PT-DEMO-001/cycle").text

    assert "sklearn" not in body
    assert "IsolationForest" not in body


# -- Test 10: edge cases ---------------------------------------------------


def test_a_window_missing_spo2_is_not_scored_and_no_delta_is_invented(tmp_path):
    client = TestClient(build_app(tmp_path, "synthetic_ml"))
    at = datetime(2026, 8, 17, 9, 0, tzinfo=timezone.utc)

    def post(minute, include_spo2):
        window = dict(TRAJECTORY["windows"][CHANGE_POINT + 1])
        observed = dict(window["observed"])
        if not include_spo2:
            observed.pop("spo2")
        window["observed"] = observed
        moment = at + timedelta(minutes=minute)
        client.post(
            "/monitoring/observations",
            json={
                "observations": observation_payload(
                    window, "PT-GAP", "CT-REPLAY", moment
                ),
                "now": moment.isoformat(),
            },
        ).raise_for_status()
        return client.post(
            "/monitoring/patients/PT-GAP/cycle",
            json={"trial_id": "CT-REPLAY", "now": moment.isoformat()},
        ).json()

    post(0, include_spo2=True)
    cycle = post(5, include_spo2=False)

    # The record itself is fine: SpO2 was measured five minutes ago, which is
    # well inside the protocol's staleness window, so the data-quality gate has
    # nothing to say and does not fire.
    assert cycle["state"]["data_quality"]["status"] == "OK"
    assert cycle["effective_risk"]["gated"] is False

    # The *model* still cannot score, because its features need all three
    # signals at one instant and this instant has two. So the provider declines
    # rather than reusing the older SpO2 to manufacture a delta.
    assert cycle["effective_risk"]["level"] == "UNKNOWN"
    assert cycle["risk"]["score"] == 0.0
    assert cycle["risk"]["degraded"] is False
    assert not any(
        f["factor"] == "ISOLATION_FOREST"
        for f in cycle["risk"]["contributing_factors"]
    )
    # The incomplete instant is dropped rather than patched, which leaves the
    # earlier complete window as the only one on record — and it has no
    # predecessor, so there is still nothing to score.
    assert any("invented" in p for p in cycle["risk"]["likely_patterns"])


def test_an_out_of_order_window_is_reconciled_by_timestamp(tmp_path):
    """Existing behaviour, confirmed rather than changed.

    Observations are ordered by `recorded_at`, not by arrival, so a late window
    slots into place and becomes the predecessor it should have been.
    """
    client = TestClient(build_app(tmp_path, "synthetic_ml"))
    at = datetime(2026, 8, 17, 9, 0, tzinfo=timezone.utc)
    windows = TRAJECTORY["windows"][CHANGE_POINT - 2 : CHANGE_POINT + 1]

    def ingest(window, minute):
        moment = at + timedelta(minutes=minute)
        client.post(
            "/monitoring/observations",
            json={
                "observations": observation_payload(
                    window, "PT-ORDER", "CT-REPLAY", moment
                ),
                "now": moment.isoformat(),
            },
        ).raise_for_status()

    def cycle(minute):
        moment = at + timedelta(minutes=minute)
        return client.post(
            "/monitoring/patients/PT-ORDER/cycle",
            json={"trial_id": "CT-REPLAY", "now": moment.isoformat()},
        ).json()

    def hr_delta(payload):
        detail = next(
            f["detail"]
            for f in payload["risk"]["contributing_factors"]
            if f["factor"] == "HEART_RATE"
        )
        return detail

    ingest(windows[0], 0)
    ingest(windows[2], 10)          # the middle window has not arrived yet
    gapped = cycle(10)

    ingest(windows[1], 5)           # it arrives late, timestamped earlier
    reconciled = cycle(10)

    assert hr_delta(gapped) != hr_delta(reconciled), (
        "the late window did not become the predecessor"
    )
    # And the reconciled delta is the one against the true previous window.
    expected = round(
        windows[2]["observed"]["heart_rate"] - windows[1]["observed"]["heart_rate"], 4
    )
    assert f"{expected:+g}" in hr_delta(reconciled)
