"""Replay a held-out synthetic patient through the running application.

    .venv/bin/python scripts/live_trajectory_demo.py
    .venv/bin/python scripts/live_trajectory_demo.py --from 96 --to 126
    .venv/bin/python scripts/live_trajectory_demo.py --all --compact

Every window is POSTed to `/monitoring/observations` and evaluated by
`/monitoring/patients/{id}/cycle`. The scores below come from the serialised
Isolation Forest reading the physiology that just arrived; nothing about the
outcome is written into this script.

The trajectory is `P0014` from the evaluation half of the research patient
split — never seen during fitting — replayed unmodified at the 5-minute cadence
the model was trained on.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from scripts.trajectory_replay import (  # noqa: E402
    DEFAULT_PATIENT,
    ReplayWindow,
    build_app,
    load_trajectory,
    replay,
)

RULE = "=" * 66


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="first", type=int, default=None)
    parser.add_argument("--to", dest="last", type=int, default=None)
    parser.add_argument(
        "--all", action="store_true", help="replay the whole 144-window trajectory"
    )
    parser.add_argument(
        "--compact", action="store_true", help="one line per window"
    )
    args = parser.parse_args()

    trajectory = load_trajectory()
    change_point = trajectory["change_point_window"]

    if args.all:
        first, last = 0, len(trajectory["windows"]) - 1
    else:
        first = args.first if args.first is not None else change_point - 7
        last = args.last if args.last is not None else change_point + 8

    with tempfile.TemporaryDirectory() as tmp:
        client = TestClient(build_app(Path(tmp), "synthetic_ml"))
        model = client.get("/monitoring/model").json()

        print()
        print(RULE)
        print("LIVE SYNTHETIC PATIENT REPLAY")
        print(f"Patient:   {DEFAULT_PATIENT}  (research trajectory "
              f"{trajectory['patient_id']}, {trajectory['scenario']})")
        print(f"Model:     {model['model_version']}  "
              f"sha256 {model['artifact']['model_sha256'][:16]}…")
        print(f"Provider:  {model['provider']}   live_inference="
              f"{model['live_inference']}")
        print(f"Cadence:   {trajectory['window_minutes']} minutes")
        print(f"Windows:   {first}–{last}   ground-truth change point: "
              f"{change_point}")
        print(RULE)

        windows = replay(client, trajectory, first=first, last=last)

        if args.compact:
            _compact(windows, change_point)
        else:
            for window in windows:
                _verbose(window, change_point)

        _summary(windows, change_point, client)

    return 0


def _fmt(value: float | None, spec: str = "+.1f") -> str:
    return "—" if value is None else format(value, spec)


def _verbose(w: ReplayWindow, change_point: int) -> None:
    marker = "  <-- ground-truth deterioration begins" if w.window_index == change_point else ""
    print()
    print(f"Window {w.window_index:02d}   {w.timestamp:%H:%M}{marker}")
    print(f"HR={w.heart_rate:<6.1f} SpO2={w.spo2:<6.1f} RR={w.respiratory_rate:<6.1f}")
    print(
        f"ΔHR={_fmt(w.heart_rate_delta):<7} "
        f"ΔSpO2={_fmt(w.spo2_delta):<7} "
        f"ΔRR={_fmt(w.respiratory_rate_delta):<7}"
    )
    if w.scored:
        print(f"Score={w.anomaly_score:+.6f}")
        print(f"Prediction={'ANOMALY' if w.predicted_anomaly else 'NORMAL'}")
    else:
        print("Score=—        (no previous window; no delta was invented)")
        print("Prediction=—")
    print(f"Risk={w.risk_level}" + (f"   (model said {w.provider_level}, gated)" if w.gated else ""))
    if w.transition:
        print(f"  transition: {w.transition}")
    if w.interventions:
        print(f"  protocol:   {', '.join(w.interventions)}")


def _compact(windows: list[ReplayWindow], change_point: int) -> None:
    print()
    print(
        f"{'win':>4} {'time':>6}  {'HR':>6} {'SpO2':>6} {'RR':>6}  "
        f"{'ΔHR':>7} {'ΔSpO2':>7} {'ΔRR':>7}  {'score':>10} {'pred':>7}  {'risk':<8} state"
    )
    print("-" * 108)
    for w in windows:
        mark = " *" if w.window_index == change_point else "  "
        score = "—" if not w.scored else f"{w.anomaly_score:+.6f}"
        pred = "—" if not w.scored else ("ANOMALY" if w.predicted_anomaly else "NORMAL")
        print(
            f"{w.window_index:>4}{mark}{w.timestamp:%H:%M}  "
            f"{w.heart_rate:>6.1f} {w.spo2:>6.1f} {w.respiratory_rate:>6.1f}  "
            f"{_fmt(w.heart_rate_delta):>7} {_fmt(w.spo2_delta):>7} "
            f"{_fmt(w.respiratory_rate_delta):>7}  "
            f"{score:>10} {pred:>7}  {w.risk_level:<8} {w.ground_truth_state}"
        )


def _summary(windows: list[ReplayWindow], change_point: int, client) -> None:
    scored = [w for w in windows if w.scored]
    before = [w for w in scored if w.window_index < change_point]
    after = [w for w in scored if w.window_index >= change_point]

    print()
    print(RULE)
    print("SUMMARY")
    print(RULE)
    print(f"windows replayed        {len(windows)}  "
          f"({len(scored)} scoreable, {len(windows) - len(scored)} without a predecessor)")
    if before:
        rate = sum(w.predicted_anomaly for w in before) / len(before)
        print(f"before change point     {len(before):>3} windows, "
              f"{rate:.0%} flagged by the model")
    if after:
        rate = sum(w.predicted_anomaly for w in after) / len(after)
        print(f"after change point      {len(after):>3} windows, "
              f"{rate:.0%} flagged by the model")

    runs, previous = [], None
    for w in windows:
        if w.risk_level != previous:
            runs.append([w.risk_level, 0])
            previous = w.risk_level
        runs[-1][1] += 1
    print("effective risk path     "
          + " -> ".join(f"{level}×{count}" for level, count in runs))

    providers = {w.risk_provider for w in windows}
    print(f"risk provider           {', '.join(sorted(providers))}")
    print(f"model version           {', '.join(sorted({w.model_version for w in windows}))}")
    print(f"data quality            {', '.join(sorted({w.data_quality for w in windows}))}")
    print(f"gated windows           {sum(w.gated for w in windows)}")

    timeline = client.get(f"/monitoring/patients/{DEFAULT_PATIENT}/timeline").json()
    kinds: dict[str, int] = {}
    for event in timeline:
        kinds[event["event_type"]] = kinds.get(event["event_type"], 0) + 1
    print("timeline events         "
          + ", ".join(f"{k}×{v}" for k, v in sorted(kinds.items())))
    print(RULE)
    print()


if __name__ == "__main__":
    raise SystemExit(main())
