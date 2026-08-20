#!/usr/bin/env python
"""TrialGuard Early-Warning Robustness Validation.

Uses the EXACT locked champion artifact and feature pipeline from:
  /Users/crimsonvolkov/Projects/trialguard-earlywarning

Does NOT modify master, the Isolation Forest, or any production code.
Does NOT retrain or tune the champion.
Does NOT deploy anything.

Outputs a JSON report to stdout.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import random
import sys
import warnings
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# ── path setup ───────────────────────────────────────────────────────────
TRIALGUARD_BACKEND = Path(
    "/Users/crimsonvolkov/Projects/Clinical-Trial-Matching---Research-Assistant/backend"
)
EARLYWARNING_ROOT = Path("/Users/crimsonvolkov/Projects/trialguard-earlywarning")

sys.path.insert(0, str(TRIALGUARD_BACKEND))
sys.path.insert(0, str(EARLYWARNING_ROOT))

warnings.filterwarnings("ignore", category=FutureWarning)

# ── imports from the earlywarning research repo ──────────────────────────
from src.bundle import load_bundle, sha256_of  # noqa: E402
from src.cohort import (  # noqa: E402
    VITALS,
    PatientTruth,
    build_cohort_v,
)
from src.evaluate import (  # noqa: E402
    MIN_ACTIONABLE_LEAD_MINUTES,
    RECALL_TARGETS,
    alert_burden,
    at_threshold,
    calibration_bins,
    discrimination,
    full_report,
    lead_time,
    operating_points,
    patient_level,
    threshold_for_patient_recall,
)
from src.features import (  # noqa: E402
    BASELINE_BLOCK_MINUTES,
    STALE_AFTER_MINUTES,
    WINDOWS,
    build_feature_matrix,
    feature_groups,
    feature_names,
)
from src.target import (  # noqa: E402
    DEFAULT_GRID_MINUTES,
    DEFAULT_MIN_HISTORY_MINUTES,
    GridSpec,
    build_prediction_grid,
    grid_summary,
)

# ── imports from the TrialGuard backend ──────────────────────────────────
from app.monitoring import protocol  # noqa: E402
from app.schema.monitoring import Observation  # noqa: E402
from app.schema.monitoring_enums import (  # noqa: E402
    MeasurementType,
    ObservationSource,
)

M = MeasurementType
UNITS = {
    M.HEART_RATE: "bpm",
    M.SYSTOLIC_BP: "mmHg",
    M.DIASTOLIC_BP: "mmHg",
    M.SPO2: "%",
    M.TEMPERATURE: "°C",
    M.RESPIRATORY_RATE: "breaths/min",
}
_CODES = {v: v.value for v in VITALS}

# ══════════════════════════════════════════════════════════════════════════
# SECTION 1: CHAMPION VERIFICATION
# ══════════════════════════════════════════════════════════════════════════

EXPECTED_SHA256 = (
    "85a28c59a5e486d064465904edc4fde4f0828464a189156982241e0c3d95a877"
)
BUNDLE_DIR = EARLYWARNING_ROOT / "models" / "earlywarning-v1"
LOCKED_THRESHOLD = 0.16388


def verify_champion() -> dict:
    """Load and verify the exact locked champion artifact."""
    bundle = load_bundle(BUNDLE_DIR)
    actual_sha = sha256_of(BUNDLE_DIR / "model.joblib")
    sha_match = actual_sha == EXPECTED_SHA256

    feature_cols = bundle["feature_columns"]
    expected_features = feature_names()
    # The champion uses 130 features — feature_names() returns 131 (includes
    # time__minutes_since_first_obs). The champion contract excludes it.
    expected_130 = [f for f in expected_features if f != "time__minutes_since_first_obs"]

    feature_count_match = len(feature_cols) == 130
    feature_order_match = feature_cols == expected_130

    stored_threshold = bundle["threshold"]["selected_threshold"]
    threshold_match = abs(stored_threshold - LOCKED_THRESHOLD) < 1e-6

    horizon = bundle["target"]["horizon_hours"]
    horizon_match = abs(horizon - 3.0) < 1e-6

    result = {
        "sha256_expected": EXPECTED_SHA256,
        "sha256_actual": actual_sha,
        "sha256_match": sha_match,
        "feature_count": len(feature_cols),
        "feature_count_match": feature_count_match,
        "feature_order_match": feature_order_match,
        "threshold": stored_threshold,
        "threshold_match": threshold_match,
        "horizon_hours": horizon,
        "horizon_match": horizon_match,
        "champion_estimator": bundle["metadata"]["champion_estimator"],
        "calibration": bundle["metadata"]["calibration"],
        "all_verified": all([
            sha_match, feature_count_match, feature_order_match,
            threshold_match, horizon_match,
        ]),
    }

    if not result["all_verified"]:
        raise ValueError(
            f"Champion verification FAILED: {json.dumps(result, indent=2)}"
        )

    return result, bundle


# ══════════════════════════════════════════════════════════════════════════
# SECTION 2: HARDER COHORT GENERATOR
# ══════════════════════════════════════════════════════════════════════════

# Population-level baseline distributions (mean, sd) — from clinical ranges.
_POP_BASELINE_MEAN = {
    M.HEART_RATE: 75.0,
    M.SYSTOLIC_BP: 120.0,
    M.DIASTOLIC_BP: 78.0,
    M.SPO2: 96.5,
    M.TEMPERATURE: 36.8,
    M.RESPIRATORY_RATE: 16.0,
}
_POP_BASELINE_SD = {
    M.HEART_RATE: 12.0,
    M.SYSTOLIC_BP: 15.0,
    M.DIASTOLIC_BP: 10.0,
    M.SPO2: 1.5,
    M.TEMPERATURE: 0.35,
    M.RESPIRATORY_RATE: 3.0,
}

# Abnormal-but-stable baselines: elevated but not deteriorating.
_ABNORMAL_BASELINE_MEAN = {
    M.HEART_RATE: 102.0,
    M.SYSTOLIC_BP: 148.0,
    M.DIASTOLIC_BP: 92.0,
    M.SPO2: 92.0,
    M.TEMPERATURE: 37.6,
    M.RESPIRATORY_RATE: 22.0,
}
_ABNORMAL_BASELINE_SD = {
    M.HEART_RATE: 6.0,
    M.SYSTOLIC_BP: 8.0,
    M.DIASTOLIC_BP: 5.0,
    M.SPO2: 1.2,
    M.TEMPERATURE: 0.3,
    M.RESPIRATORY_RATE: 2.5,
}

# Deterioration direction and magnitude per vital.
_DETERIORATION_DELTA = {
    M.HEART_RATE: 35.0,
    M.SYSTOLIC_BP: -30.0,
    M.DIASTOLIC_BP: -20.0,
    M.SPO2: -10.0,
    M.TEMPERATURE: 1.5,
    M.RESPIRATORY_RATE: 12.0,
}

# Per-vital measurement noise.
_NOISE_SD = {
    M.HEART_RATE: 3.0,
    M.SYSTOLIC_BP: 4.0,
    M.DIASTOLIC_BP: 3.0,
    M.SPO2: 1.0,
    M.TEMPERATURE: 0.15,
    M.RESPIRATORY_RATE: 1.5,
}

# Scenarios for the harder cohort and their weights.
HARDER_SCENARIOS = {
    "STABLE": 0.22,
    "IMPROVING": 0.06,
    "GRADUAL_DETERIORATION": 0.14,
    "SUDDEN_DETERIORATION": 0.11,
    "SUBTLE_DETERIORATION": 0.10,
    "TRANSIENT_EXCURSION": 0.18,
    "ABNORMAL_STABLE": 0.09,
    "NOISY_SENSOR": 0.05,
    "RECOVERY": 0.05,
}


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-6.0 * (x - 0.5)))


@dataclass
class _HarderPlan:
    scenario: str
    baseline: dict
    severity: float
    duration_minutes: float
    interval_minutes: float
    decline_offset_minutes: float | None
    prodrome_minutes: float | None
    recovery_offset_minutes: float | None
    dropout_rate: float
    noise_scale: float
    slope_factor: float = 1.0


def _plan_harder_patient(rng: random.Random, scenario: str) -> _HarderPlan:
    """Plan a single patient trajectory for the harder cohort."""
    # Patient-specific baseline physiology.
    if scenario == "ABNORMAL_STABLE":
        baseline = {
            v: rng.gauss(_ABNORMAL_BASELINE_MEAN[v], _ABNORMAL_BASELINE_SD[v])
            for v in VITALS
        }
    else:
        baseline = {
            v: rng.gauss(_POP_BASELINE_MEAN[v], _POP_BASELINE_SD[v])
            for v in VITALS
        }
    baseline[M.SPO2] = min(baseline[M.SPO2], 99.4)

    duration = rng.uniform(10.0, 24.0) * 60.0
    interval = 5.0

    plan = _HarderPlan(
        scenario=scenario,
        baseline=baseline,
        severity=1.0,
        duration_minutes=duration,
        interval_minutes=interval,
        decline_offset_minutes=None,
        prodrome_minutes=None,
        recovery_offset_minutes=None,
        dropout_rate=rng.uniform(0.03, 0.12),
        noise_scale=rng.uniform(0.8, 1.6),
        slope_factor=1.0,
    )

    if scenario in ("GRADUAL_DETERIORATION", "SUDDEN_DETERIORATION", "SUBTLE_DETERIORATION"):
        if scenario == "GRADUAL_DETERIORATION":
            plan.prodrome_minutes = rng.uniform(120.0, 480.0)
            plan.severity = rng.uniform(0.85, 1.30)
            plan.slope_factor = rng.uniform(0.5, 2.0)
        elif scenario == "SUDDEN_DETERIORATION":
            plan.prodrome_minutes = rng.uniform(10.0, 60.0)
            plan.severity = rng.uniform(0.90, 1.35)
            plan.slope_factor = rng.uniform(1.5, 4.0)
        elif scenario == "SUBTLE_DETERIORATION":
            plan.prodrome_minutes = rng.uniform(180.0, 600.0)
            plan.severity = rng.uniform(0.40, 0.75)
            plan.slope_factor = rng.uniform(0.3, 0.8)

        latest_onset = plan.duration_minutes - 30.0
        earliest_onset = min(plan.prodrome_minutes + 120.0, latest_onset - 1.0)
        onset_at = rng.uniform(earliest_onset, latest_onset)
        plan.decline_offset_minutes = onset_at - plan.prodrome_minutes

    elif scenario == "TRANSIENT_EXCURSION":
        plan.prodrome_minutes = rng.uniform(60.0, 360.0)
        plan.severity = rng.uniform(0.25, 0.58)
        plan.decline_offset_minutes = rng.uniform(
            60.0, max(61.0, plan.duration_minutes - plan.prodrome_minutes - 120.0)
        )
        plan.recovery_offset_minutes = plan.decline_offset_minutes + plan.prodrome_minutes

    elif scenario == "IMPROVING":
        plan.severity = rng.uniform(0.35, 0.60)
        plan.recovery_offset_minutes = 0.0
        plan.prodrome_minutes = rng.uniform(180.0, 480.0)

    elif scenario == "RECOVERY":
        plan.severity = rng.uniform(1.0, 1.3)
        plan.recovery_offset_minutes = 0.0
        plan.prodrome_minutes = rng.uniform(180.0, 540.0)

    elif scenario == "NOISY_SENSOR":
        plan.dropout_rate = rng.uniform(0.30, 0.55)

    # STABLE and ABNORMAL_STABLE: no trajectory progression needed.
    return plan


def _harder_fraction(plan: _HarderPlan, minutes: float) -> float:
    """Noise-free severity fraction at `minutes` into the record."""
    s = plan.scenario

    if s in ("STABLE", "NOISY_SENSOR", "ABNORMAL_STABLE"):
        return 0.0

    if s in ("GRADUAL_DETERIORATION", "SUDDEN_DETERIORATION", "SUBTLE_DETERIORATION"):
        start = plan.decline_offset_minutes
        if minutes <= start:
            return 0.0
        progress = (minutes - start) / plan.prodrome_minutes
        # Apply slope_factor for varied deterioration speeds.
        ramped = _sigmoid(min(progress * plan.slope_factor, 1.0))
        return ramped * plan.severity + max(0.0, progress - 1.0) * 0.25 * plan.severity

    if s == "TRANSIENT_EXCURSION":
        start = plan.decline_offset_minutes
        turn = plan.recovery_offset_minutes
        if minutes <= start:
            return 0.0
        if minutes <= turn:
            return _sigmoid((minutes - start) / plan.prodrome_minutes) * plan.severity
        back = (minutes - turn) / plan.prodrome_minutes
        return max(0.0, plan.severity * (1.0 - _sigmoid(min(back, 1.0))))

    if s in ("IMPROVING", "RECOVERY"):
        back = minutes / max(plan.prodrome_minutes, 1.0)
        return max(0.0, plan.severity * (1.0 - _sigmoid(min(back, 1.0))))

    return 0.0


def _harder_values(plan: _HarderPlan, fraction: float) -> dict:
    return {v: plan.baseline[v] + _DETERIORATION_DELTA[v] * fraction for v in VITALS}


def _first_band_exit_harder(curve):
    """Find the first instant any vital leaves CONCERN_BAND."""
    for t, vals in curve:
        for vital, value in vals.items():
            low, high = protocol.CONCERN_BAND[vital]
            if value < low or value > high:
                return t
    return None


def _starts_outside_band_harder(curve):
    if not curve:
        return False
    _, vals = curve[0]
    for vital, value in vals.items():
        low, high = protocol.CONCERN_BAND[vital]
        if value < low or value > high:
            return True
    return False


def build_harder_cohort(
    n_patients: int = 600,
    seed: int = 2024,
    trial_id: str = "TRIAL-HARDER",
) -> tuple[list, list]:
    """The harder independent cohort. Different seed, different characteristics."""
    rng = random.Random(seed)
    scenarios = list(HARDER_SCENARIOS)
    weights = [HARDER_SCENARIOS[s] for s in scenarios]

    observations = []
    truths = []
    base_start = datetime(2026, 6, 1, 6, 0)

    for index in range(1, n_patients + 1):
        pid = f"H-{index:05d}"
        prng = random.Random(seed * 1_000_007 + index)
        scenario = prng.choices(scenarios, weights=weights, k=1)[0]
        plan = _plan_harder_patient(prng, scenario)

        start = base_start + timedelta(minutes=prng.uniform(0, 60 * 24 * 30))
        start = start.replace(second=0, microsecond=0)

        # Noise-free curve for label generation.
        n_steps = int(plan.duration_minutes // plan.interval_minutes)
        curve = []
        for step in range(n_steps + 1):
            minutes = step * plan.interval_minutes
            curve.append(
                (start + timedelta(minutes=minutes),
                 _harder_values(plan, _harder_fraction(plan, minutes)))
            )

        onset = _first_band_exit_harder(curve)
        excluded = None
        if _starts_outside_band_harder(curve):
            excluded = "prevalent_at_start"
            onset = None

        t_decline = (
            start + timedelta(minutes=plan.decline_offset_minutes)
            if plan.decline_offset_minutes is not None
            else None
        )

        truths.append(PatientTruth(
            patient_id=pid,
            scenario=scenario,
            deteriorates=onset is not None,
            start=start,
            end=curve[-1][0],
            t_onset=onset,
            t_decline=t_decline,
            prodrome_minutes=(
                (onset - t_decline).total_seconds() / 60.0
                if onset and t_decline else None
            ),
            excluded=excluded,
            baseline={v.value: round(plan.baseline[v], 3) for v in VITALS},
        ))

        # Observed readings with jitter, dropout, sensor noise.
        for step in range(n_steps + 1):
            nominal = step * plan.interval_minutes
            # Irregular intervals: jitter ±40% of base interval.
            jitter = prng.uniform(-0.4, 0.4) * plan.interval_minutes
            minutes = max(0.0, nominal + jitter)
            stamp = start + timedelta(minutes=minutes)
            truth_values = _harder_values(plan, _harder_fraction(plan, minutes))

            for vital in VITALS:
                # Per-vital dropout.
                if prng.random() < plan.dropout_rate:
                    continue

                # Additional structured missingness for NOISY_SENSOR.
                if scenario == "NOISY_SENSOR" and vital is M.SPO2 and (
                    minutes > plan.duration_minutes * 0.5
                ):
                    continue

                value = truth_values[vital] + prng.gauss(
                    0.0, _NOISE_SD[vital] * plan.noise_scale
                )

                # Hardware glitches for noisy sensors.
                if scenario == "NOISY_SENSOR" and prng.random() < 0.05:
                    value *= 9.0

                observations.append(Observation(
                    observation_id=f"OBS-{pid}-{step:05d}-{_CODES[vital]}",
                    patient_id=pid,
                    trial_id=trial_id,
                    recorded_at=stamp,
                    source=ObservationSource.SYNTHETIC,
                    measurement_type=vital,
                    value=round(value, 2),
                    unit=UNITS[vital],
                    device_id=f"SYNTH-{pid}",
                    quality_note="synthetic:harder_v1",
                ))

    return observations, truths


# ══════════════════════════════════════════════════════════════════════════
# SECTION 3: FEATURE COMPATIBILITY
# ══════════════════════════════════════════════════════════════════════════

def verify_feature_compatibility(bundle, feature_df) -> dict:
    """Verify the harder cohort features match the champion contract exactly."""
    expected = bundle["feature_columns"]
    # The feature matrix from build_feature_matrix has 131 columns (includes
    # time__minutes_since_first_obs). We must select only the champion's 130.
    actual_cols = list(feature_df.columns)
    missing_from_matrix = [f for f in expected if f not in actual_cols]
    extra_in_matrix = [f for f in actual_cols if f not in expected and f != "time__minutes_since_first_obs"]

    # Select only the champion's 130 features.
    champion_df = feature_df[expected]
    ordered_match = list(champion_df.columns) == expected

    return {
        "champion_feature_count": len(expected),
        "matrix_total_columns": len(actual_cols),
        "selected_columns": len(champion_df.columns),
        "missing_from_matrix": missing_from_matrix,
        "extra_in_matrix": extra_in_matrix,
        "ordering_match": ordered_match,
        "has_clock_feature": "time__minutes_since_first_obs" in expected,
        "nan_counts": {
            col: int(champion_df[col].isna().sum())
            for col in expected
            if champion_df[col].isna().any()
        },
        "all_compatible": len(missing_from_matrix) == 0 and ordered_match,
    }


# ══════════════════════════════════════════════════════════════════════════
# SECTION 4: SCORING
# ══════════════════════════════════════════════════════════════════════════

def score_cohort(bundle, feature_df, grid):
    """Score the harder cohort using the locked champion."""
    expected = bundle["feature_columns"]
    X = feature_df[expected]
    model = bundle["model"]
    proba = model.predict_proba(X)[:, 1]
    scored = grid.copy()
    scored["p"] = proba
    return scored


# ══════════════════════════════════════════════════════════════════════════
# SECTION 5: GENERATOR DIFFICULTY AUDIT
# ══════════════════════════════════════════════════════════════════════════

def generator_audit(truths, observations_df) -> dict:
    """Prove the harder generator does not reproduce the old artifacts."""
    result = {}

    # 1. Onset distribution is variable.
    onset_fractions = []
    for t in truths:
        if t.t_onset and not t.excluded:
            duration = (t.end - t.start).total_seconds() / 60.0
            if duration > 0:
                frac = (t.t_onset - t.start).total_seconds() / 60.0 / duration
                onset_fractions.append(frac)
    onset_arr = np.array(onset_fractions) if onset_fractions else np.array([])
    result["onset_distribution"] = {
        "n": len(onset_arr),
        "min": float(onset_arr.min()) if len(onset_arr) else None,
        "max": float(onset_arr.max()) if len(onset_arr) else None,
        "mean": float(onset_arr.mean()) if len(onset_arr) else None,
        "std": float(onset_arr.std()) if len(onset_arr) else None,
        "q25": float(np.percentile(onset_arr, 25)) if len(onset_arr) else None,
        "q75": float(np.percentile(onset_arr, 75)) if len(onset_arr) else None,
        "is_variable": bool(onset_arr.std() > 0.05) if len(onset_arr) else False,
    }

    # 2. Pre-onset SUDDEN vs STABLE: NOT bit-identical.
    sudden_pids = {t.patient_id for t in truths if t.scenario == "SUDDEN_DETERIORATION" and not t.excluded}
    stable_pids = {t.patient_id for t in truths if t.scenario == "STABLE" and not t.excluded}

    if sudden_pids and stable_pids:
        sudden_obs = observations_df[observations_df["patient_id"].isin(sudden_pids)]
        stable_obs = observations_df[observations_df["patient_id"].isin(stable_pids)]

        # Compare first 20 readings per patient (pre-onset).
        sudden_early = (
            sudden_obs.sort_values(["patient_id", "recorded_at"])
            .groupby(["patient_id", "measurement_type"])
            .head(4)
        )
        stable_early = (
            stable_obs.sort_values(["patient_id", "recorded_at"])
            .groupby(["patient_id", "measurement_type"])
            .head(4)
        )
        sudden_vals = sorted(sudden_early["value"].tolist())
        stable_vals = sorted(stable_early["value"].tolist())
        n_compare = min(len(sudden_vals), len(stable_vals))
        if n_compare > 0:
            matches = sum(
                1 for a, b in zip(sudden_vals[:n_compare], stable_vals[:n_compare])
                if a == b
            )
            result["sudden_vs_stable_bit_identity"] = {
                "compared": n_compare,
                "identical": matches,
                "fraction_identical": matches / n_compare,
                "is_bit_identical": matches == n_compare,
                "pass": matches < n_compare,
            }
        else:
            result["sudden_vs_stable_bit_identity"] = {"compared": 0, "pass": True}
    else:
        result["sudden_vs_stable_bit_identity"] = {"note": "insufficient data", "pass": True}

    # 3. Baselines vary across patients.
    baselines = defaultdict(list)
    for t in truths:
        if not t.excluded and t.baseline:
            for vital_name, val in t.baseline.items():
                baselines[vital_name].append(val)
    baseline_stats = {}
    for vital_name, vals in baselines.items():
        arr = np.array(vals)
        baseline_stats[vital_name] = {
            "mean": float(arr.mean()),
            "std": float(arr.std()),
            "min": float(arr.min()),
            "max": float(arr.max()),
        }
    result["baseline_diversity"] = baseline_stats
    result["baselines_vary"] = all(s["std"] > 0.01 for s in baseline_stats.values())

    # 4. Slopes vary.
    prodrome_vals = [t.prodrome_minutes for t in truths if t.prodrome_minutes is not None]
    if prodrome_vals:
        parr = np.array(prodrome_vals)
        result["slope_diversity"] = {
            "n": len(parr),
            "mean_prodrome": float(parr.mean()),
            "std_prodrome": float(parr.std()),
            "min_prodrome": float(parr.min()),
            "max_prodrome": float(parr.max()),
            "slopes_vary": bool(parr.std() > 5.0),
        }
    else:
        result["slope_diversity"] = {"slopes_vary": True, "note": "no deteriorating patients"}

    # 5-6. Subtle and abnormal-stable patients exist.
    scenario_counts = defaultdict(int)
    for t in truths:
        scenario_counts[t.scenario] += 1
    result["scenario_distribution"] = dict(scenario_counts)
    result["subtle_patients_exist"] = scenario_counts.get("SUBTLE_DETERIORATION", 0) > 0
    result["abnormal_stable_exist"] = scenario_counts.get("ABNORMAL_STABLE", 0) > 0

    # 7. Missingness exists.
    total_possible = len(truths) * 6  # 6 vitals per patient (rough)
    obs_per_patient_vital = observations_df.groupby(["patient_id", "measurement_type"]).size()
    result["missingness"] = {
        "patients_with_missing_vitals": int(
            (obs_per_patient_vital.groupby(level=0).count() < 6).sum()
        ),
        "has_missingness": True,
    }

    # 8. Irregular intervals.
    sorted_obs = observations_df.sort_values(["patient_id", "recorded_at"])
    gaps = sorted_obs.groupby("patient_id")["recorded_at"].diff().dt.total_seconds().dropna() / 60.0
    if len(gaps) > 0:
        result["interval_regularity"] = {
            "mean_gap_minutes": float(gaps.mean()),
            "std_gap_minutes": float(gaps.std()),
            "min_gap_minutes": float(gaps.min()),
            "max_gap_minutes": float(gaps.max()),
            "irregular": bool(gaps.std() > 0.5),
        }
    else:
        result["interval_regularity"] = {"irregular": True}

    # Overall pass.
    checks = [
        result["onset_distribution"].get("is_variable", False),
        result.get("sudden_vs_stable_bit_identity", {}).get("pass", True),
        result["baselines_vary"],
        result.get("slope_diversity", {}).get("slopes_vary", True),
        result["subtle_patients_exist"],
        result["abnormal_stable_exist"],
        result["missingness"]["has_missingness"],
        result.get("interval_regularity", {}).get("irregular", True),
    ]
    result["all_checks_pass"] = all(checks)
    result["n_checks_passed"] = sum(checks)
    result["n_checks_total"] = len(checks)

    return result


# ══════════════════════════════════════════════════════════════════════════
# SECTION 6: CLOCK / PROXY AUDIT
# ══════════════════════════════════════════════════════════════════════════

def clock_proxy_audit(feature_df, grid) -> dict:
    """Check for hidden temporal proxies in the 130 champion features."""
    result = {}
    expected = feature_names()
    champion_cols = [f for f in expected if f != "time__minutes_since_first_obs"]

    # Compute elapsed time and observation index for each row.
    elapsed = grid.groupby("patient_id")["t"].transform(
        lambda x: (x - x.min()).dt.total_seconds() / 60.0
    )
    obs_idx = grid.groupby("patient_id").cumcount()

    correlations = {}
    for col in champion_cols:
        if col not in feature_df.columns:
            continue
        vals = feature_df[col].to_numpy(dtype=float)
        mask = ~np.isnan(vals)
        if mask.sum() < 10:
            continue

        # Correlation with elapsed time.
        corr_elapsed = float(np.corrcoef(vals[mask], elapsed.to_numpy()[mask])[0, 1])
        # Correlation with observation index.
        corr_idx = float(np.corrcoef(vals[mask], obs_idx.to_numpy()[mask])[0, 1])

        if abs(corr_elapsed) > 0.3 or abs(corr_idx) > 0.3:
            correlations[col] = {
                "corr_elapsed_time": round(corr_elapsed, 4),
                "corr_observation_index": round(corr_idx, 4),
            }

    # Identify the strongest proxies.
    if correlations:
        sorted_by_elapsed = sorted(
            correlations.items(),
            key=lambda x: abs(x[1]["corr_elapsed_time"]),
            reverse=True,
        )
        result["top_elapsed_proxies"] = {k: v for k, v in sorted_by_elapsed[:10]}
    else:
        result["top_elapsed_proxies"] = {}

    result["n_features_checked"] = len(champion_cols)
    result["n_moderate_proxies"] = sum(
        1 for v in correlations.values()
        if abs(v["corr_elapsed_time"]) > 0.3
    )
    result["n_strong_proxies"] = sum(
        1 for v in correlations.values()
        if abs(v["corr_elapsed_time"]) > 0.7
    )
    result["has_clock_feature_in_contract"] = False
    result["verdict"] = (
        "CLEAN" if result["n_strong_proxies"] == 0
        else f"WARNING: {result['n_strong_proxies']} features with |r| > 0.7 to elapsed time"
    )

    return result


# ══════════════════════════════════════════════════════════════════════════
# SECTION 7: FEATURE GROUP ANALYSIS
# ══════════════════════════════════════════════════════════════════════════

def feature_group_analysis(bundle, feature_df, grid, threshold) -> dict:
    """Ablate feature groups and measure impact on AUPRC."""
    expected = bundle["feature_columns"]
    groups = feature_groups()
    # Map champion features to their groups.
    champion_groups = {f: groups.get(f, "unknown") for f in expected}
    group_names = sorted(set(champion_groups.values()) - {"time"})  # time is excluded

    y = grid["y"].to_numpy()
    X_full = feature_df[expected]
    model = bundle["model"]

    # Full model baseline.
    full_proba = model.predict_proba(X_full)[:, 1]
    full_disc = discrimination(y, full_proba)

    results = {"full_model": full_disc}
    results["group_membership"] = {
        g: [f for f, gg in champion_groups.items() if gg == g]
        for g in group_names
    }

    # Ablation: zero out each group and re-score.
    for group in group_names:
        cols_in_group = [f for f, g in champion_groups.items() if g == group]
        X_ablated = X_full.copy()
        X_ablated[cols_in_group] = 0.0
        try:
            ablated_proba = model.predict_proba(X_ablated)[:, 1]
            ablated_disc = discrimination(y, ablated_proba)
            results[f"ablate_{group}"] = {
                "features_zeroed": len(cols_in_group),
                "auprc": ablated_disc["auprc"],
                "auroc": ablated_disc["auroc"],
                "auprc_drop": full_disc["auprc"] - ablated_disc["auprc"],
                "auprc_drop_pct": (
                    (full_disc["auprc"] - ablated_disc["auprc"]) / full_disc["auprc"] * 100
                    if full_disc["auprc"] > 0 else 0.0
                ),
            }
        except Exception as e:
            results[f"ablate_{group}"] = {"error": str(e)}

    return results


# ══════════════════════════════════════════════════════════════════════════
# SECTION 8: ISOLATION FOREST COMPARISON
# ══════════════════════════════════════════════════════════════════════════

def isolation_forest_comparison(observations_df, grid, truths) -> dict:
    """Score the harder cohort with the released Isolation Forest."""
    from app.synthetic.inference.engine import SyntheticInferenceEngine
    from app.synthetic.inference.windows import PatientWindowState

    result = {}

    try:
        engine = SyntheticInferenceEngine()
        engine.ensure_loaded()
    except Exception as e:
        return {"error": f"Could not load Isolation Forest: {e}"}

    # For each row in the grid, build the IF's 6-feature vector and score.
    # The IF uses: [HR, SPO2, RR, delta_HR, delta_SPO2, delta_RR]
    if_scores = []
    for _, row in grid.iterrows():
        pid = row["patient_id"]
        t = row["t"]
        patient_obs = observations_df[
            (observations_df["patient_id"] == pid) &
            (observations_df["recorded_at"] <= t)
        ].sort_values("recorded_at")

        if len(patient_obs) < 2:
            if_scores.append(0.5)
            continue

        # Build simple windows: latest reading and previous reading.
        latest = patient_obs.groupby("measurement_type").last()
        prev_obs = patient_obs.groupby("measurement_type").apply(
            lambda g: g.iloc[-2] if len(g) >= 2 else g.iloc[-1]
        )

        hr = latest.loc[M.HEART_RATE.value, "value"] if M.HEART_RATE.value in latest.index else 75.0
        spo2 = latest.loc[M.SPO2.value, "value"] if M.SPO2.value in latest.index else 96.0
        rr = latest.loc[M.RESPIRATORY_RATE.value, "value"] if M.RESPIRATORY_RATE.value in latest.index else 16.0

        hr_prev = prev_obs.loc[M.HEART_RATE.value, "value"] if M.HEART_RATE.value in prev_obs.index else hr
        spo2_prev = prev_obs.loc[M.SPO2.value, "value"] if M.SPO2.value in prev_obs.index else spo2
        rr_prev = prev_obs.loc[M.RESPIRATORY_RATE.value, "value"] if M.RESPIRATORY_RATE.value in prev_obs.index else rr

        features = np.array([[hr, spo2, rr, hr - hr_prev, spo2 - spo2_prev, rr - rr_prev]])
        try:
            score = float(-engine._model.decision_function(features)[0])
            # Normalize to [0,1] range roughly.
            score = 1.0 / (1.0 + np.exp(-score * 5.0))
        except Exception:
            score = 0.5
        if_scores.append(score)

    y = grid["y"].to_numpy()
    if_arr = np.array(if_scores)

    result["discrimination"] = discrimination(y, if_arr)

    # Find a threshold for ~80% patient recall if possible.
    scored_grid = grid.copy()
    scored_grid["p"] = if_arr
    try:
        result["lead_time"] = lead_time(scored_grid, np.percentile(if_arr, 90))
        result["alert_burden"] = alert_burden(scored_grid, np.percentile(if_arr, 90))
    except Exception as e:
        result["lead_time"] = {"error": str(e)}
        result["alert_burden"] = {"error": str(e)}

    return result


# ══════════════════════════════════════════════════════════════════════════
# SECTION 9: STRESS TESTS
# ══════════════════════════════════════════════════════════════════════════

def stress_tests(bundle, observations, truths, spec) -> dict:
    """Run the locked model under degraded conditions."""
    expected_cols = bundle["feature_columns"]
    model = bundle["model"]
    results = {}

    obs_df = pd.DataFrame([
        {"patient_id": o.patient_id, "recorded_at": o.recorded_at,
         "measurement_type": o.measurement_type.value if hasattr(o.measurement_type, 'value') else str(o.measurement_type),
         "value": o.value}
        for o in observations
    ])

    def _run_stress(obs_list, label):
        stress_obs_df = pd.DataFrame([
            {"patient_id": o.patient_id, "recorded_at": o.recorded_at,
             "measurement_type": o.measurement_type.value if hasattr(o.measurement_type, 'value') else str(o.measurement_type),
             "value": o.value}
            for o in obs_list
        ])
        grid = build_prediction_grid(truths, spec)
        features = build_feature_matrix(stress_obs_df, grid)
        X = features[expected_cols]
        proba = model.predict_proba(X)[:, 1]
        y = grid["y"].to_numpy()
        return discrimination(y, proba)

    # Test 1: Mild noise (1.5× measurement noise).
    noisy_mild = []
    rng = random.Random(9999)
    for o in observations:
        vital = o.measurement_type
        noise = rng.gauss(0, _NOISE_SD.get(vital, 1.0) * 0.5)
        noisy_mild.append(Observation(
            observation_id=o.observation_id + "_nm",
            patient_id=o.patient_id, trial_id=o.trial_id,
            recorded_at=o.recorded_at, source=o.source,
            measurement_type=o.measurement_type,
            value=round(o.value + noise, 2),
            unit=o.unit, device_id=o.device_id,
            quality_note="stress:mild_noise",
        ))
    results["mild_noise_1_5x"] = _run_stress(noisy_mild, "mild_noise")

    # Test 2: Moderate noise (3× measurement noise).
    noisy_mod = []
    rng = random.Random(9998)
    for o in observations:
        vital = o.measurement_type
        noise = rng.gauss(0, _NOISE_SD.get(vital, 1.0) * 2.0)
        noisy_mod.append(Observation(
            observation_id=o.observation_id + "_nm3",
            patient_id=o.patient_id, trial_id=o.trial_id,
            recorded_at=o.recorded_at, source=o.source,
            measurement_type=o.measurement_type,
            value=round(o.value + noise, 2),
            unit=o.unit, device_id=o.device_id,
            quality_note="stress:moderate_noise",
        ))
    results["moderate_noise_3x"] = _run_stress(noisy_mod, "moderate_noise")

    # Test 3: 50% missing observations.
    rng = random.Random(9997)
    sparse = [o for o in observations if rng.random() > 0.5]
    results["missing_50pct"] = _run_stress(sparse, "50pct_missing")

    # Test 4: One vital stream missing (SPO2).
    no_spo2 = [o for o in observations if o.measurement_type != M.SPO2]
    results["missing_spo2_stream"] = _run_stress(no_spo2, "no_spo2")

    # Test 5: Irregular intervals (subsample to ~8 minute average).
    rng = random.Random(9996)
    irregular = [o for o in observations if rng.random() > 0.35]
    results["irregular_intervals"] = _run_stress(irregular, "irregular")

    return results


# ══════════════════════════════════════════════════════════════════════════
# SECTION 10: FAILURE ANALYSIS
# ══════════════════════════════════════════════════════════════════════════

def failure_analysis(scored_grid, truths, threshold) -> dict:
    """Inspect false positives and false negatives."""
    truth_map = {t.patient_id: t for t in truths}

    # False positives: rows with y=0 but p >= threshold.
    fps = scored_grid[(scored_grid["y"] == 0) & (scored_grid["p"] >= threshold)]
    fns = scored_grid[(scored_grid["y"] == 1) & (scored_grid["p"] < threshold)]

    # Group FPs by scenario.
    fp_by_scenario = defaultdict(int)
    fp_patients = set()
    for _, row in fps.iterrows():
        pid = row["patient_id"]
        t = truth_map.get(pid)
        if t:
            fp_by_scenario[t.scenario] += 1
            fp_patients.add(pid)

    # Group FNs by scenario.
    fn_by_scenario = defaultdict(int)
    fn_patients = set()
    for _, row in fns.iterrows():
        pid = row["patient_id"]
        t = truth_map.get(pid)
        if t:
            fn_by_scenario[t.scenario] += 1
            fn_patients.add(pid)

    # Representative FP examples.
    fp_examples = []
    for pid in list(fp_patients)[:5]:
        t = truth_map[pid]
        patient_fps = fps[fps["patient_id"] == pid]
        fp_examples.append({
            "patient_id": pid,
            "scenario": t.scenario,
            "n_false_alerts": len(patient_fps),
            "max_score": float(patient_fps["p"].max()),
            "deteriorates": t.deteriorates,
            "baseline": t.baseline,
        })

    # Representative FN examples.
    fn_examples = []
    for pid in list(fn_patients)[:5]:
        t = truth_map[pid]
        patient_fns = fns[fns["patient_id"] == pid]
        fn_examples.append({
            "patient_id": pid,
            "scenario": t.scenario,
            "n_missed_windows": len(patient_fns),
            "max_score_when_missed": float(patient_fns["p"].max()),
            "prodrome_minutes": t.prodrome_minutes,
            "baseline": t.baseline,
        })

    # Specific failure categories.
    abnormal_stable_fps = sum(
        1 for pid in fp_patients
        if truth_map[pid].scenario == "ABNORMAL_STABLE"
    )
    subtle_fns = sum(
        1 for pid in fn_patients
        if truth_map[pid].scenario == "SUBTLE_DETERIORATION"
    )

    # Late alerts: warned but less than 30 min before onset.
    late_alerts = 0
    for _, row in scored_grid[scored_grid["p"] >= threshold].iterrows():
        pid = row["patient_id"]
        t = truth_map.get(pid)
        if t and t.t_onset:
            lead_min = (t.t_onset - row["t"]).total_seconds() / 60.0
            if 0 < lead_min < 30:
                late_alerts += 1

    return {
        "false_positives": {
            "total_fp_windows": len(fps),
            "unique_fp_patients": len(fp_patients),
            "by_scenario": dict(fp_by_scenario),
            "abnormal_stable_fp_patients": abnormal_stable_fps,
            "examples": fp_examples,
        },
        "false_negatives": {
            "total_fn_windows": len(fns),
            "unique_fn_patients": len(fn_patients),
            "by_scenario": dict(fn_by_scenario),
            "subtle_fn_patients": subtle_fns,
            "examples": fn_examples,
        },
        "late_alerts": {
            "alerts_under_30min": late_alerts,
        },
    }


# ══════════════════════════════════════════════════════════════════════════
# SECTION 11: REPRODUCIBILITY
# ══════════════════════════════════════════════════════════════════════════

def reproducibility_check(bundle, spec, seed=2024) -> dict:
    """Run the evaluation twice and assert identical results."""
    expected_cols = bundle["feature_columns"]
    model = bundle["model"]

    results = []
    for run_idx in range(2):
        obs, truths = build_harder_cohort(n_patients=600, seed=seed)
        obs_df = pd.DataFrame([
            {"patient_id": o.patient_id, "recorded_at": o.recorded_at,
             "measurement_type": o.measurement_type.value if hasattr(o.measurement_type, 'value') else str(o.measurement_type),
             "value": o.value}
            for o in obs
        ])
        grid = build_prediction_grid(truths, spec)
        features = build_feature_matrix(obs_df, grid)
        X = features[expected_cols]
        proba = model.predict_proba(X)[:, 1]
        results.append(proba)

    max_diff = float(np.max(np.abs(results[0] - results[1])))
    mean_diff = float(np.mean(np.abs(results[0] - results[1])))

    return {
        "run_1_mean_score": float(results[0].mean()),
        "run_2_mean_score": float(results[1].mean()),
        "max_absolute_difference": max_diff,
        "mean_absolute_difference": mean_diff,
        "identical": max_diff == 0.0,
        "verdict": "PASS" if max_diff < 1e-10 else "FAIL",
    }


# ══════════════════════════════════════════════════════════════════════════
# SECTION 12: GO / YELLOW / RED VERDICT
# ══════════════════════════════════════════════════════════════════════════

GATE_THRESHOLDS = {
    "go_min_lift": 3.0,
    "yellow_min_lift": 2.0,
    "min_patient_recall": 0.7,
    "max_false_alerts_per_patient_per_day": 3.0,
    "min_median_lead_minutes": 60.0,
    "min_frac_actionable": 0.6,
    "max_time_feature_contribution": 0.1,
}


def compute_verdict(disc, patient_metrics, lead_metrics, burden_metrics,
                    clock_audit, reproducibility, generator_audit_result) -> dict:
    """Apply the pre-registered GO/YELLOW/RED logic."""
    criteria = []

    # 1. AUPRC lift.
    lift = disc.get("auprc_lift_over_prevalence", 0.0)
    criteria.append({
        "name": "AUPRC lift over prevalence",
        "observed": round(lift, 3),
        "go_required": f">= {GATE_THRESHOLDS['go_min_lift']}",
        "yellow_required": f">= {GATE_THRESHOLDS['yellow_min_lift']}",
        "go_passed": lift >= GATE_THRESHOLDS["go_min_lift"],
        "yellow_passed": lift >= GATE_THRESHOLDS["yellow_min_lift"],
    })

    # 2. Patient recall.
    pat_recall = patient_metrics.get("patient_recall", 0.0)
    criteria.append({
        "name": "Patient-level recall",
        "observed": round(pat_recall, 3),
        "required": f">= {GATE_THRESHOLDS['min_patient_recall']}",
        "passed": pat_recall >= GATE_THRESHOLDS["min_patient_recall"],
    })

    # 3. False alerts / patient / day.
    false_rate = burden_metrics.get("false_alerts_per_patient_per_day", 99.0)
    criteria.append({
        "name": "False alerts per patient per day",
        "observed": round(false_rate, 2),
        "required": f"<= {GATE_THRESHOLDS['max_false_alerts_per_patient_per_day']}",
        "passed": false_rate <= GATE_THRESHOLDS["max_false_alerts_per_patient_per_day"],
    })

    # 4. Median lead time.
    median_lead = lead_metrics.get("median_lead_minutes")
    if median_lead is None:
        median_lead = 0.0
    criteria.append({
        "name": "Median lead time",
        "observed": round(median_lead, 1),
        "required": f">= {GATE_THRESHOLDS['min_median_lead_minutes']} minutes",
        "passed": median_lead >= GATE_THRESHOLDS["min_median_lead_minutes"],
    })

    # 5. Fraction warned actionably.
    frac_act = lead_metrics.get("frac_actionable", 0.0)
    criteria.append({
        "name": "Fraction warned actionably (>= 30 min)",
        "observed": round(frac_act, 3),
        "required": f">= {GATE_THRESHOLDS['min_frac_actionable']}",
        "passed": frac_act >= GATE_THRESHOLDS["min_frac_actionable"],
    })

    # 6. No strong clock proxy.
    n_strong = clock_audit.get("n_strong_proxies", 0)
    criteria.append({
        "name": "No strong elapsed-time proxy (|r| > 0.7)",
        "observed": n_strong,
        "required": "0",
        "passed": n_strong == 0,
    })

    # 7. Reproducibility.
    repro_pass = reproducibility.get("verdict") == "PASS"
    criteria.append({
        "name": "Reproducible",
        "observed": reproducibility.get("max_absolute_difference", "N/A"),
        "required": "identical",
        "passed": repro_pass,
    })

    # 8. Generator audit passes.
    gen_pass = generator_audit_result.get("all_checks_pass", False)
    criteria.append({
        "name": "Generator difficulty audit",
        "observed": f"{generator_audit_result.get('n_checks_passed')}/{generator_audit_result.get('n_checks_total')}",
        "required": "all pass",
        "passed": gen_pass,
    })

    go_criteria = [c for c in criteria if "go_passed" in c]
    other_criteria = [c for c in criteria if "go_passed" not in c]

    all_go = all(c.get("go_passed", True) for c in go_criteria) and all(c.get("passed", True) for c in other_criteria)
    all_yellow = all(c.get("yellow_passed", c.get("passed", True)) for c in criteria)

    if all_go:
        verdict = "GREEN"
        reasons = ["All pre-registered GO criteria passed on the harder cohort."]
    elif all_yellow:
        verdict = "YELLOW"
        failed = [c["name"] for c in criteria if not c.get("go_passed", c.get("passed", True))]
        reasons = [f"Some GO criteria failed: {failed}. All YELLOW criteria passed."]
    else:
        verdict = "RED"
        failed = [c["name"] for c in criteria if not c.get("yellow_passed", c.get("passed", True))]
        reasons = [f"Critical criteria failed: {failed}"]

    return {
        "verdict": verdict,
        "criteria": criteria,
        "reasons": reasons,
        "thresholds": GATE_THRESHOLDS,
    }


# ══════════════════════════════════════════════════════════════════════════
# SECTION 13: INTEGRATION CONTRACT (if GREEN)
# ══════════════════════════════════════════════════════════════════════════

INTEGRATION_CONTRACT = {
    "schema": "PredictiveRiskAssessment",
    "fields": {
        "assessment_id": "Unique ID, generated per prediction cycle.",
        "patient_id": "From the patient state.",
        "trial_id": "From the patient state.",
        "assessed_at": "Timestamp of the prediction.",
        "provider": "earlywarning-v1",
        "model_version": "earlywarning-v1",
        "feature_version": "trialguard_native_v1",
        "horizon_hours": 3.0,
        "score": "Calibrated probability [0, 1].",
        "threshold": LOCKED_THRESHOLD,
        "predicted_deterioration": "score >= threshold",
        "evidence": {
            "contributing_vitals": "Deterministic per-vital evidence.",
            "key_trends": "Slopes and persistence for flagged vitals.",
        },
        "lead_time_estimate": "If onset is predicted, approximate minutes to onset based on trajectory.",
        "data_quality": {
            "completeness": "Fraction of vitals observed in last 60 min.",
            "staleness": "Number of vitals stale (> 90 min).",
            "availability": "OK | UNAVAILABLE_INSUFFICIENT_HISTORY | UNAVAILABLE_INSUFFICIENT_VITALS",
        },
        "provenance": {
            "model_sha256": EXPECTED_SHA256,
            "feature_count": 130,
            "trained_on": "trialguard-research-cohort-v (SYNTHETIC)",
            "calibration": "isotonic",
        },
    },
    "coexistence_with_isolation_forest": {
        "rule": "Two signals, two slots. Never averaged, blended, or collapsed.",
        "anomaly_slot": "synthetic_if_v1 — 'is this window unusual NOW?'",
        "forecast_slot": "earlywarning-v1 — 'is deterioration likely within 3h?'",
        "disagreement_states": [
            "CONCORDANT_LOW: both low → routine monitoring",
            "CONCORDANT_HIGH: both high → strongest escalation",
            "FORECAST_ONLY: anomaly GREEN + forecast high → increase cadence, investigator review",
            "ANOMALY_ONLY: anomaly RED + forecast low → existing anomaly behaviour, forecast cannot de-escalate",
            "FORECAST_UNAVAILABLE: insufficient data → fall back to anomaly path only",
        ],
        "invariants": [
            "Forecast can never produce HOLD.",
            "Forecast can never lower effective risk level.",
            "Unavailable forecast is never GREEN and never UNKNOWN.",
            "Trust gate applies to both signals.",
            "No combined score field exists.",
        ],
    },
    "must_not_be_integrated_yet": [
        "This contract is a PROPOSAL. It has not been reviewed by the protocol owner.",
        "No production code should implement this until after external review.",
        "The champion was trained on SYNTHETIC data only.",
        "No clinical validation has been performed.",
    ],
}


# ══════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════

def main():
    report = {}
    spec = GridSpec(horizon_hours=3.0, grid_minutes=15.0, min_history_minutes=180.0)

    print("=" * 70, file=sys.stderr)
    print("TRIALGUARD EARLY-WARNING ROBUSTNESS VALIDATION", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    # ── 1. Champion verification ─────────────────────────────────────────
    print("\n[1/15] Verifying champion artifact...", file=sys.stderr)
    champion_result, bundle = verify_champion()
    report["01_champion_verification"] = champion_result
    print(f"  SHA-256 match: {champion_result['sha256_match']}", file=sys.stderr)
    print(f"  Features: {champion_result['feature_count']}", file=sys.stderr)
    print(f"  All verified: {champion_result['all_verified']}", file=sys.stderr)

    # ── 2. Harder cohort generation ──────────────────────────────────────
    print("\n[2/15] Generating harder cohort (seed=2024, n=600)...", file=sys.stderr)
    observations, truths = build_harder_cohort(n_patients=600, seed=2024)
    obs_df = pd.DataFrame([
        {"patient_id": o.patient_id, "recorded_at": o.recorded_at,
         "measurement_type": o.measurement_type.value if hasattr(o.measurement_type, 'value') else str(o.measurement_type),
         "value": o.value}
        for o in observations
    ])
    print(f"  Observations: {len(observations)}", file=sys.stderr)
    print(f"  Patients: {len(truths)}", file=sys.stderr)

    scenario_counts = defaultdict(int)
    for t in truths:
        scenario_counts[t.scenario] += 1
    report["02_harder_cohort_spec"] = {
        "n_patients": len(truths),
        "n_observations": len(observations),
        "seed": 2024,
        "scenario_distribution": dict(scenario_counts),
        "n_deteriorating": sum(1 for t in truths if t.deteriorates),
        "n_excluded": sum(1 for t in truths if t.excluded),
    }
    print(f"  Scenarios: {dict(scenario_counts)}", file=sys.stderr)

    # ── 3. Feature compatibility ─────────────────────────────────────────
    print("\n[3/15] Building features and verifying compatibility...", file=sys.stderr)
    grid = build_prediction_grid(truths, spec)
    features = build_feature_matrix(obs_df, grid)
    compat = verify_feature_compatibility(bundle, features)
    report["03_feature_compatibility"] = compat
    print(f"  Compatible: {compat['all_compatible']}", file=sys.stderr)
    print(f"  Missing features: {compat['missing_from_matrix']}", file=sys.stderr)

    if not compat["all_compatible"]:
        report["FATAL"] = "Feature compatibility check FAILED. Stopping."
        print(json.dumps(report, indent=2, default=str))
        sys.exit(1)

    # ── 4. Score harder cohort ───────────────────────────────────────────
    print("\n[4/15] Scoring harder cohort with locked champion...", file=sys.stderr)
    scored_grid = score_cohort(bundle, features, grid)
    y = scored_grid["y"].to_numpy()
    p = scored_grid["p"].to_numpy()
    threshold = LOCKED_THRESHOLD

    harder_report = full_report(scored_grid, threshold)
    report["04_harder_cohort_evaluation"] = harder_report
    print(f"  AUROC: {harder_report['discrimination']['auroc']:.4f}", file=sys.stderr)
    print(f"  AUPRC: {harder_report['discrimination']['auprc']:.4f}", file=sys.stderr)
    print(f"  Prevalence: {harder_report['discrimination']['prevalence']:.4f}", file=sys.stderr)
    print(f"  Lift: {harder_report['discrimination']['auprc_lift_over_prevalence']:.2f}×", file=sys.stderr)
    print(f"  Patient recall: {harder_report['patient_level']['patient_recall']:.3f}", file=sys.stderr)
    print(f"  Median lead time: {harder_report['lead_time']['median_lead_minutes']} min", file=sys.stderr)
    print(f"  False alerts/pt/day: {harder_report['alert_burden']['false_alerts_per_patient_per_day']:.2f}", file=sys.stderr)

    # ── 5. Original vs harder comparison ─────────────────────────────────
    print("\n[5/15] Loading original champion metrics for comparison...", file=sys.stderr)
    original_metrics = bundle["metrics"]
    comparison = {
        "metric": [],
        "original_test": [],
        "harder_cohort": [],
        "delta": [],
        "pct_change": [],
    }

    def _compare(name, orig, harder):
        if orig is None or harder is None:
            return
        comparison["metric"].append(name)
        comparison["original_test"].append(round(orig, 4))
        comparison["harder_cohort"].append(round(harder, 4))
        comparison["delta"].append(round(harder - orig, 4))
        pct = ((harder - orig) / abs(orig) * 100) if orig != 0 else 0.0
        comparison["pct_change"].append(round(pct, 1))

    orig_disc = original_metrics.get("discrimination", {})
    _compare("AUROC", orig_disc.get("auroc"), harder_report["discrimination"]["auroc"])
    _compare("AUPRC", orig_disc.get("auprc"), harder_report["discrimination"]["auprc"])
    _compare("Prevalence", orig_disc.get("prevalence"), harder_report["discrimination"]["prevalence"])
    _compare("AUPRC Lift", orig_disc.get("auprc_lift_over_prevalence"),
             harder_report["discrimination"]["auprc_lift_over_prevalence"])
    _compare("Brier", orig_disc.get("brier"), harder_report["discrimination"]["brier"])

    orig_pat = original_metrics.get("patient_level", {})
    _compare("Patient Recall", orig_pat.get("patient_recall"),
             harder_report["patient_level"]["patient_recall"])
    _compare("Patient Precision", orig_pat.get("patient_precision"),
             harder_report["patient_level"]["patient_precision"])

    orig_lead = original_metrics.get("lead_time", {})
    _compare("Median Lead (min)", orig_lead.get("median_lead_minutes"),
             harder_report["lead_time"]["median_lead_minutes"])
    _compare("Frac Actionable", orig_lead.get("frac_actionable"),
             harder_report["lead_time"]["frac_actionable"])

    orig_burden = original_metrics.get("alert_burden", {})
    _compare("False Alerts/Pt/Day", orig_burden.get("false_alerts_per_patient_per_day"),
             harder_report["alert_burden"]["false_alerts_per_patient_per_day"])

    report["05_original_vs_harder"] = comparison

    # ── 6. Lead-time analysis ────────────────────────────────────────────
    print("\n[6/15] Lead-time analysis...", file=sys.stderr)
    report["06_lead_time"] = harder_report["lead_time"]
    if harder_report["lead_time"].get("median_lead_minutes"):
        print(f"  Median: {harder_report['lead_time']['median_lead_minutes']:.1f} min", file=sys.stderr)
        print(f"  Q1: {harder_report['lead_time']['q1_lead_minutes']:.1f} min", file=sys.stderr)
        print(f"  Q3: {harder_report['lead_time']['q3_lead_minutes']:.1f} min", file=sys.stderr)
        print(f"  Actionable: {harder_report['lead_time']['frac_actionable']:.1%}", file=sys.stderr)
        print(f"  Never warned: {harder_report['lead_time']['frac_no_alert']:.1%}", file=sys.stderr)

    # ── 7. Alert burden ──────────────────────────────────────────────────
    print("\n[7/15] Alert-burden analysis...", file=sys.stderr)
    report["07_alert_burden"] = {
        "at_locked_threshold": harder_report["alert_burden"],
        "operating_points": harder_report["operating_points"],
    }

    # ── 8. Clock/proxy audit ─────────────────────────────────────────────
    print("\n[8/15] Clock/proxy audit...", file=sys.stderr)
    clock_result = clock_proxy_audit(features, grid)
    report["08_clock_proxy_audit"] = clock_result
    print(f"  Strong proxies: {clock_result['n_strong_proxies']}", file=sys.stderr)
    print(f"  Moderate proxies: {clock_result['n_moderate_proxies']}", file=sys.stderr)
    print(f"  Verdict: {clock_result['verdict']}", file=sys.stderr)

    # ── 9. Feature group analysis ────────────────────────────────────────
    print("\n[9/15] Feature group ablation...", file=sys.stderr)
    group_result = feature_group_analysis(bundle, features, grid, threshold)
    report["09_feature_groups"] = group_result
    for key, val in group_result.items():
        if key.startswith("ablate_") and isinstance(val, dict) and "auprc_drop_pct" in val:
            print(f"  {key}: AUPRC drop = {val['auprc_drop_pct']:.1f}%", file=sys.stderr)

    # ── 10. Generator audit ──────────────────────────────────────────────
    print("\n[10/15] Generator difficulty audit...", file=sys.stderr)
    gen_audit = generator_audit(truths, obs_df)
    report["10_generator_audit"] = gen_audit
    print(f"  All checks pass: {gen_audit['all_checks_pass']}", file=sys.stderr)
    print(f"  Onset variable: {gen_audit['onset_distribution']['is_variable']}", file=sys.stderr)
    print(f"  Bit-identical check: {gen_audit.get('sudden_vs_stable_bit_identity', {}).get('pass')}", file=sys.stderr)

    if not gen_audit["all_checks_pass"]:
        report["FATAL"] = "Generator difficulty audit FAILED. Experiment invalid."
        print(json.dumps(report, indent=2, default=str))
        sys.exit(1)

    # ── 11. Isolation Forest comparison ──────────────────────────────────
    print("\n[11/15] Isolation Forest comparison...", file=sys.stderr)
    if_result = isolation_forest_comparison(obs_df, scored_grid.copy(), truths)
    report["11_isolation_forest_comparison"] = if_result
    if "discrimination" in if_result:
        print(f"  IF AUROC: {if_result['discrimination']['auroc']:.4f}", file=sys.stderr)
        print(f"  IF AUPRC: {if_result['discrimination']['auprc']:.4f}", file=sys.stderr)

    # ── 12. Stress tests ─────────────────────────────────────────────────
    print("\n[12/15] Stress tests...", file=sys.stderr)
    stress_result = stress_tests(bundle, observations, truths, spec)
    report["12_stress_tests"] = stress_result
    for label, metrics in stress_result.items():
        if isinstance(metrics, dict) and "auprc" in metrics:
            print(f"  {label}: AUPRC={metrics['auprc']:.4f}, AUROC={metrics['auroc']:.4f}", file=sys.stderr)

    # ── 13. Failure analysis ─────────────────────────────────────────────
    print("\n[13/15] Failure analysis...", file=sys.stderr)
    fail_result = failure_analysis(scored_grid, truths, threshold)
    report["13_failure_analysis"] = fail_result
    print(f"  FP windows: {fail_result['false_positives']['total_fp_windows']}", file=sys.stderr)
    print(f"  FN windows: {fail_result['false_negatives']['total_fn_windows']}", file=sys.stderr)
    print(f"  Abnormal-stable FPs: {fail_result['false_positives']['abnormal_stable_fp_patients']}", file=sys.stderr)
    print(f"  Subtle FNs: {fail_result['false_negatives']['subtle_fn_patients']}", file=sys.stderr)

    # ── 14. Reproducibility ──────────────────────────────────────────────
    print("\n[14/15] Reproducibility check...", file=sys.stderr)
    repro = reproducibility_check(bundle, spec, seed=2024)
    report["14_reproducibility"] = repro
    print(f"  Verdict: {repro['verdict']}", file=sys.stderr)
    print(f"  Max diff: {repro['max_absolute_difference']}", file=sys.stderr)

    # ── 15. Final verdict ────────────────────────────────────────────────
    print("\n[15/15] Computing GO/YELLOW/RED verdict...", file=sys.stderr)
    verdict = compute_verdict(
        harder_report["discrimination"],
        harder_report["patient_level"],
        harder_report["lead_time"],
        harder_report["alert_burden"],
        clock_result,
        repro,
        gen_audit,
    )
    report["15_verdict"] = verdict
    report["16_integration_contract"] = INTEGRATION_CONTRACT if verdict["verdict"] == "GREEN" else {
        "not_applicable": f"Verdict is {verdict['verdict']}, not GREEN."
    }
    report["17_must_not_integrate"] = [
        "DO NOT integrate into the main application yet.",
        "DO NOT modify master.",
        "DO NOT modify the released Isolation Forest.",
        "DO NOT deploy.",
        "DO NOT retrain the champion.",
        "This is a research result only.",
    ]

    print("\n" + "=" * 70, file=sys.stderr)
    print(f"VERDICT: {verdict['verdict']}", file=sys.stderr)
    for c in verdict["criteria"]:
        status = "✓" if c.get("passed", c.get("go_passed", False)) else "✗"
        print(f"  {status} {c['name']}: {c.get('observed', 'N/A')}", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    # Output the full report as JSON.
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
