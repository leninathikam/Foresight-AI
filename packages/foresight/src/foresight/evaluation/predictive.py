"""Held-out evaluation of failure-risk prediction, anomaly / change detection, and diagnosis.

Everything is computed from the test split (disjoint seeds); thresholds that need tuning are
chosen on the validation split only.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import numpy as np
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_recall_fscore_support,
    roc_auc_score,
)

from foresight.prediction.dataset import DIAGNOSIS_CLASSES, HORIZONS_MIN, Dataset
from foresight.prediction.features import FEATURE_NAMES
from foresight.prediction.models import CUSUM_SIGNALS, RiskBundle, run_cusum

_TEMP = FEATURE_NAMES.index("temperature_c")
_VIB = FEATURE_NAMES.index("vibration_mm_s")
_TTL = FEATURE_NAMES.index("minutes_to_temp_limit")
_ZSCORE_FEATURES = [
    i
    for i, n in enumerate(FEATURE_NAMES)
    if n not in ("missing_fraction", "minutes_to_temp_limit", "speed_frac")
]

ScoreFn = Callable[[np.ndarray], np.ndarray]


def _round(x: float | None, nd: int = 4) -> float | None:
    if x is None or not np.isfinite(x):
        return None
    return round(float(x), nd)


def expected_calibration_error(y: np.ndarray, p: np.ndarray, n_bins: int = 10) -> float:
    bins = np.clip((p * n_bins).astype(int), 0, n_bins - 1)
    ece = 0.0
    for b in range(n_bins):
        m = bins == b
        if m.any():
            ece += m.mean() * abs(y[m].mean() - p[m].mean())
    return float(ece)


def reliability_bins(y: np.ndarray, p: np.ndarray, n_bins: int = 10) -> list[dict]:
    bins = np.clip((p * n_bins).astype(int), 0, n_bins - 1)
    out = []
    for b in range(n_bins):
        m = bins == b
        if m.any():
            out.append(
                {
                    "bin_low": b / n_bins,
                    "bin_high": (b + 1) / n_bins,
                    "count": int(m.sum()),
                    "mean_predicted": _round(p[m].mean()),
                    "observed_frequency": _round(y[m].mean()),
                }
            )
    return out


def _best_f1_threshold(y: np.ndarray, score: np.ndarray) -> float:
    candidates = np.unique(np.quantile(score, np.linspace(0.5, 0.999, 200)))
    best_t, best_f = float(candidates[0]), -1.0
    for t in candidates:
        f = f1_score(y, score >= t, zero_division=0)
        if f > best_f:
            best_t, best_f = float(t), f
    return best_t


def _episode_alarm_stats(ds: Dataset, alarm: np.ndarray) -> dict:
    """First-alarm lead time on failing episodes and false-alarm rates on the rest."""
    lead_times, detected, failing = [], 0, 0
    nonfail_alarmed, nonfail = 0, 0
    healthy_alarmed, healthy = 0, 0
    false_alarm_rows, nonfail_hours = 0, 0.0
    for i, ep in enumerate(ds.episodes):
        m = ds.episode == i
        a = alarm[m]
        t = ds.t_s[m]
        if ep.failure_time_s is not None:
            failing += 1
            if a.any():
                detected += 1
                lead_times.append((ep.failure_time_s - t[np.argmax(a)]) / 60.0)
        else:
            nonfail += 1
            nonfail_alarmed += int(a.any())
            false_alarm_rows += int(a.sum())
            nonfail_hours += len(t) / 60.0
            if ep.scenario.value == "healthy":
                healthy += 1
                healthy_alarmed += int(a.any())
    lt = np.array(lead_times) if lead_times else np.array([np.nan])
    return {
        "failing_episodes": failing,
        "failing_detected": detected,
        "episode_detection_rate": _round(detected / failing) if failing else None,
        "lead_time_min_median": _round(np.nanmedian(lt), 1),
        "lead_time_min_p10": _round(np.nanpercentile(lt, 10), 1),
        "lead_time_min_p90": _round(np.nanpercentile(lt, 90), 1),
        "non_failing_episodes": nonfail,
        "non_failing_episodes_with_alarm": nonfail_alarmed,
        "healthy_episodes": healthy,
        "healthy_episodes_with_alarm": healthy_alarmed,
        "false_alarm_minutes_per_operating_hour": _round(
            false_alarm_rows / nonfail_hours if nonfail_hours else None, 3
        ),
    }


def _score_methods(bundle: RiskBundle, h: int) -> dict[str, tuple[ScoreFn, bool]]:
    """name -> (score function, output is a probability)."""

    def zscore(X: np.ndarray) -> np.ndarray:
        return np.nanmax(np.abs(bundle.zscores(X)[:, _ZSCORE_FEATURES]), axis=1)

    return {
        "xgboost_calibrated": (lambda X: bundle.risk_calibrated(X, h), True),
        "xgboost_raw": (lambda X: bundle.risk_raw(X, h), True),
        "logistic_regression": (lambda X: bundle.logistic[h].predict_proba(X)[:, 1], True),
        "zscore_max": (zscore, False),
        "alarm_threshold_rule": (
            lambda X: np.maximum(X[:, _TEMP] / 130.0, X[:, _VIB] / 4.5),
            False,
        ),
        "temperature_extrapolation": (lambda X: -X[:, _TTL], False),
    }


METHOD_NOTES = {
    "xgboost_calibrated": "Gradient-boosted trees on 16 causal features, isotonic-calibrated on validation.",
    "xgboost_raw": "Same model before calibration.",
    "logistic_regression": "Supervised linear baseline (standardised features).",
    "zscore_max": "Statistical baseline: max |z| vs healthy training data; threshold tuned on validation.",
    "alarm_threshold_rule": "Conventional alarm: winding ≥ 130 °C or vibration ≥ 4.5 mm/s (no tuning).",
    "temperature_extrapolation": "Heuristic: linear 30-min temperature trend reaches 155 °C within the horizon.",
}


def evaluate_risk(bundle: RiskBundle, validation: Dataset, test: Dataset) -> dict:
    out: dict = {"horizons": {}, "method_notes": METHOD_NOTES}
    for h in HORIZONS_MIN:
        y_val, y = validation.labels[h], test.labels[h]
        methods = {}
        for name, (fn, is_prob) in _score_methods(bundle, h).items():
            s_val, s = fn(validation.X), fn(test.X)
            if name == "alarm_threshold_rule":
                thr, thr_src = 1.0, "fixed alarm limits"
            elif name == "temperature_extrapolation":
                thr, thr_src = -float(h), f"projected minutes to limit ≤ {h}"
            else:
                thr, thr_src = _best_f1_threshold(y_val, s_val), "F1-optimal on validation"
            alarm = s >= thr
            p, r, f, _ = precision_recall_fscore_support(
                y, alarm, average="binary", zero_division=0
            )
            neg = y == 0
            m = {
                "threshold": _round(thr),
                "threshold_source": thr_src,
                "precision": _round(p),
                "recall": _round(r),
                "f1": _round(f),
                "pr_auc": _round(average_precision_score(y, s)),
                "roc_auc": _round(roc_auc_score(y, s)),
                "false_positive_rate": _round(alarm[neg].mean() if neg.any() else None),
                "is_probability": is_prob,
                "brier": _round(brier_score_loss(y, np.clip(s, 0, 1))) if is_prob else None,
                "ece": _round(expected_calibration_error(y, s)) if is_prob else None,
                "episode": _episode_alarm_stats(test, alarm),
            }
            if name in ("xgboost_calibrated", "xgboost_raw"):
                m["reliability"] = reliability_bins(y, s)
            methods[name] = m
        out["horizons"][str(h)] = {
            "positives": int(y.sum()),
            "rows": len(y),
            "prevalence": _round(y.mean()),
            "methods": methods,
        }
    return out


def evaluate_detection(bundle: RiskBundle, test: Dataset) -> dict:
    """Detection delay after fault onset and false alarms for Isolation Forest and CUSUM."""
    names = ("isolation_forest", "cusum_any")
    per: dict[str, dict] = {n: {"delays_min": [], "missed": 0, "pre_onset_alarm": 0} for n in names}
    healthy_alarm = dict.fromkeys(names, 0)
    healthy_n = 0
    for i, ep in enumerate(test.episodes):
        m = test.episode == i
        X, t = test.X[m], test.t_s[m]
        iso = bundle.anomaly_scores(X) > bundle.iforest_threshold
        cus = np.zeros(len(t), dtype=bool)
        for sig in CUSUM_SIGNALS:
            j = FEATURE_NAMES.index(sig)
            drift, threshold = bundle.cusum_for(sig)
            res = run_cusum(
                X[:, j],
                float(bundle.healthy_mean[j]),
                float(bundle.healthy_std[j]),
                drift,
                threshold,
            )
            if res.alarm_index is not None:
                cus[res.alarm_index :] = True
        for name, alarm in zip(names, (iso, cus), strict=True):
            if ep.fault_onset_s is None:
                healthy_alarm[name] += int(alarm.any())
                continue
            if alarm[t < ep.fault_onset_s].any():
                per[name]["pre_onset_alarm"] += 1
            post = alarm & (t >= ep.fault_onset_s)
            if post.any():
                per[name]["delays_min"].append((t[np.argmax(post)] - ep.fault_onset_s) / 60.0)
            else:
                per[name]["missed"] += 1
        if ep.fault_onset_s is None:
            healthy_n += 1
    out = {}
    for name in names:
        d = np.array(per[name]["delays_min"]) if per[name]["delays_min"] else np.array([np.nan])
        faulted = len(per[name]["delays_min"]) + per[name]["missed"]
        out[name] = {
            "faulted_episodes": faulted,
            "detected": len(per[name]["delays_min"]),
            "missed": per[name]["missed"],
            "episodes_with_pre_onset_alarm": per[name]["pre_onset_alarm"],
            "detection_delay_min_median": _round(np.nanmedian(d), 1),
            "detection_delay_min_p90": _round(np.nanpercentile(d, 90), 1),
            "healthy_episodes": healthy_n,
            "healthy_episodes_with_alarm": healthy_alarm[name],
        }
    out["notes"] = (
        "Fault onset is the scripted initiation time; many faults are physically invisible for "
        "some time after onset, so detection delay includes the latent period."
    )
    return out


def evaluate_diagnosis(bundle: RiskBundle, test: Dataset) -> dict:
    proba = bundle.diagnosis_proba(test.X)
    pred = proba.argmax(axis=1)
    y = test.diagnosis
    onset = np.full(len(y), np.inf)
    for i, ep in enumerate(test.episodes):
        if ep.fault_onset_s is not None:
            onset[test.episode == i] = ep.fault_onset_s
    mature = (y == 0) | (test.t_s - onset >= 30 * 60)

    def block(mask: np.ndarray) -> dict:
        return {
            "rows": int(mask.sum()),
            "accuracy": _round((pred[mask] == y[mask]).mean()),
            "macro_f1": _round(f1_score(y[mask], pred[mask], average="macro", zero_division=0)),
            "confusion_matrix": confusion_matrix(
                y[mask], pred[mask], labels=list(range(len(DIAGNOSIS_CLASSES)))
            ).tolist(),
        }

    return {
        "classes": list(DIAGNOSIS_CLASSES),
        "all_rows": block(np.ones(len(y), dtype=bool)),
        "rows_30min_after_onset_or_healthy": block(mature),
        "notes": "Rows labelled with a fault right after onset are often not yet observable.",
    }


def measure_latency(bundle: RiskBundle, test: Dataset, n: int = 300) -> dict:
    X = test.X[:n]
    times = []
    for i in range(len(X)):
        row = X[i : i + 1]
        t0 = time.perf_counter()
        for h in HORIZONS_MIN:
            bundle.risk_calibrated(row, h)
        bundle.anomaly_scores(row)
        bundle.diagnosis_proba(row)
        times.append((time.perf_counter() - t0) * 1000.0)
    arr = np.array(times)
    return {
        "calls": len(arr),
        "per_assessment_ms_p50": _round(np.median(arr), 2),
        "per_assessment_ms_p95": _round(np.percentile(arr, 95), 2),
        "scope": "3 calibrated horizons + isolation forest + diagnosis for one feature row, CPU",
    }
