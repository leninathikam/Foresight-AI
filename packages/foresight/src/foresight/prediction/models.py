"""Training and runtime inference for anomaly detection, change points, and failure risk."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import sklearn
import xgboost
from sklearn.ensemble import IsolationForest
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

from foresight.prediction.changepoint import cusum
from foresight.prediction.dataset import DIAGNOSIS_CLASSES, HORIZONS_MIN, SPLIT_SEEDS, Dataset
from foresight.prediction.features import FEATURE_DESCRIPTIONS, FEATURE_NAMES, features_from_samples
from foresight.prediction.schemas import (
    AnomalyResult,
    ChangePoint,
    DiagnosisProbability,
    EvidenceItem,
    HorizonRisk,
    RiskAssessment,
)
from foresight.telemetry import TelemetrySample

# Load *level* differs between healthy episodes (process set-point), so the load signal for
# change detection is its trend, which is ~0 on any healthy run.
CUSUM_SIGNALS = ("rise_residual_k", "bearing_index", "load_slope_30m")
CUSUM_TARGET_SCENARIO = {
    "rise_residual_k": "cooling_degradation",
    "bearing_index": "bearing_deterioration",
    "load_slope_30m": "overload",
}
CUSUM_DRIFTS = (0.5, 1.0, 1.5, 2.0, 3.0, 4.0)
DEFAULT_CUSUM = (0.5, 8.0)
# Isolation-forest threshold keeps this fraction of healthy validation segments alarm-free.
HEALTHY_SEGMENT_QUANTILE = 0.95
# CUSUM threshold = margin x the largest statistic on any full healthy validation episode.
CUSUM_THRESHOLD_MARGIN = 1.1
# Assessment rows are one per minute; 30-min trend features are not valid before this.
CUSUM_WARMUP_ROWS = 30


def run_cusum(series: np.ndarray, mean: float, std: float, drift: float, threshold: float):
    """Upward-only CUSUM after the start-up period: every monitored fault raises its signal."""
    return cusum(series, mean, std, drift, threshold, skip=CUSUM_WARMUP_ROWS, upward_only=True)


EVIDENCE_UNITS = {
    "temperature_c": "°C",
    "temp_rise_k": "K",
    "temp_slope_10m": "K/min",
    "temp_slope_30m": "K/min",
    "rise_residual_k": "K",
    "vibration_mm_s": "mm/s",
    "vib_slope_30m": "mm/s/min",
    "load_frac": "× rated",
    "current_ratio": "× rated",
}


def _xgb(objective: str = "binary:logistic", **kw) -> XGBClassifier:
    return XGBClassifier(
        n_estimators=300,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=5,
        objective=objective,
        random_state=0,
        n_jobs=4,
        tree_method="hist",
        **kw,
    )


@dataclass
class RiskBundle:
    feature_names: tuple[str, ...]
    horizons: tuple[int, ...]
    iforest: IsolationForest
    iforest_threshold: float
    healthy_mean: np.ndarray
    healthy_std: np.ndarray
    risk_models: dict[int, XGBClassifier]
    calibrators: dict[int, IsotonicRegression]
    diagnosis_model: XGBClassifier
    logistic: dict[int, Pipeline]
    metadata: dict = field(default_factory=dict)
    cusum_params: dict[str, tuple[float, float]] = field(default_factory=dict)

    def cusum_for(self, signal: str) -> tuple[float, float]:
        return self.cusum_params.get(signal, DEFAULT_CUSUM)

    @property
    def version(self) -> str:
        return self.metadata.get("version", "untrained")

    # -------------------------------------------------------------- inference
    def anomaly_scores(self, X: np.ndarray) -> np.ndarray:
        return -self.iforest.score_samples(X)

    def risk_raw(self, X: np.ndarray, horizon: int) -> np.ndarray:
        return self.risk_models[horizon].predict_proba(X)[:, 1]

    def risk_calibrated(self, X: np.ndarray, horizon: int) -> np.ndarray:
        return self.calibrators[horizon].predict(self.risk_raw(X, horizon))

    def diagnosis_proba(self, X: np.ndarray) -> np.ndarray:
        return self.diagnosis_model.predict_proba(X)

    def zscores(self, X: np.ndarray) -> np.ndarray:
        return (X - self.healthy_mean) / self.healthy_std


def _episode_masks(ds: Dataset) -> list[tuple[np.ndarray, np.ndarray, float | None]]:
    """Per episode: (row mask, healthy-row mask within the episode, onset time)."""
    out = []
    for i, ep in enumerate(ds.episodes):
        m = ds.episode == i
        out.append((m, ds.diagnosis[m] == 0, ep.fault_onset_s))
    return out


def calibrate_iforest(iforest: IsolationForest, validation: Dataset) -> float:
    scores = -iforest.score_samples(validation.X)
    maxima = [scores[m][h].max() for m, h, _ in _episode_masks(validation) if h.any()]
    return float(np.quantile(maxima, HEALTHY_SEGMENT_QUANTILE))


def calibrate_cusum(
    validation: Dataset, mean: np.ndarray, std: np.ndarray
) -> tuple[dict[str, tuple[float, float]], dict[str, dict]]:
    """Choose (drift, threshold) per signal on validation: the threshold sits above every full
    healthy episode (with margin); the drift minimises median detection delay."""
    params: dict[str, tuple[float, float]] = {}
    report: dict[str, dict] = {}
    episodes = _episode_masks(validation)
    for name in CUSUM_SIGNALS:
        j = FEATURE_NAMES.index(name)
        best: tuple[float, float, float] | None = None
        for k in CUSUM_DRIFTS:
            stats, maxima = [], []
            for m, _, onset in episodes:
                res = run_cusum(validation.X[m, j], float(mean[j]), float(std[j]), k, np.inf)
                stat = res.positive
                stats.append(stat)
                # Full-length healthy runs: CUSUM maxima grow with run length, so short
                # pre-onset prefixes would understate the false-alarm threshold.
                if onset is None:
                    maxima.append(stat.max())
            h = max(5.0, CUSUM_THRESHOLD_MARGIN * float(np.max(maxima)))
            delays = []
            for ep, (m, _, onset), stat in zip(validation.episodes, episodes, stats, strict=True):
                if onset is None or ep.scenario.value != CUSUM_TARGET_SCENARIO[name]:
                    continue
                t = validation.t_s[m]
                post = (t >= onset) & (stat > h)
                delays.append((t[np.argmax(post)] - onset) / 60.0 if post.any() else 1e6)
            delay = float(np.median(delays)) if delays else 1e6
            if best is None or delay < best[2]:
                best = (k, h, delay)
        assert best is not None
        params[name] = (best[0], best[1])
        report[name] = {
            "drift": best[0],
            "threshold": round(best[1], 2),
            "median_delay_min": best[2],
        }
    return params, report


def train_bundle(train: Dataset, validation: Dataset) -> RiskBundle:
    healthy = train.diagnosis == 0
    X_h = train.X[healthy]
    mean = X_h.mean(axis=0)
    std = X_h.std(axis=0) + 1e-6

    iforest = IsolationForest(n_estimators=200, contamination="auto", random_state=0)
    iforest.fit(X_h)
    iforest_threshold = calibrate_iforest(iforest, validation)
    cusum_params, cusum_report = calibrate_cusum(validation, mean, std)

    risk_models, calibrators, logistic = {}, {}, {}
    for h in HORIZONS_MIN:
        y = train.labels[h]
        model = _xgb(eval_metric="logloss")
        model.fit(train.X, y)
        risk_models[h] = model
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        iso.fit(model.predict_proba(validation.X)[:, 1], validation.labels[h])
        calibrators[h] = iso
        lr = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000))
        lr.fit(train.X, y)
        logistic[h] = lr

    diag = _xgb(
        objective="multi:softprob", num_class=len(DIAGNOSIS_CLASSES), eval_metric="mlogloss"
    )
    diag.fit(train.X, train.diagnosis)

    digest = hashlib.sha256(train.X.tobytes())
    digest.update(json.dumps([iforest_threshold, sorted(cusum_params.items())]).encode())
    fingerprint = digest.hexdigest()[:12]
    metadata = {
        "version": f"risk-{fingerprint}",
        "trained_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "train_rows": train.n_rows,
        "validation_rows": validation.n_rows,
        "train_episodes": len(train.episodes),
        "validation_episodes": len(validation.episodes),
        "split_seeds": {k: [v.start, v.stop - 1] for k, v in SPLIT_SEEDS.items()},
        "horizons_min": list(HORIZONS_MIN),
        "feature_names": list(FEATURE_NAMES),
        "xgboost_version": xgboost.__version__,
        "sklearn_version": sklearn.__version__,
        "iforest_threshold": iforest_threshold,
        "cusum_calibration": cusum_report,
    }
    return RiskBundle(
        feature_names=FEATURE_NAMES,
        horizons=HORIZONS_MIN,
        iforest=iforest,
        iforest_threshold=iforest_threshold,
        healthy_mean=mean,
        healthy_std=std,
        risk_models=risk_models,
        calibrators=calibrators,
        diagnosis_model=diag,
        logistic=logistic,
        metadata=metadata,
        cusum_params=cusum_params,
    )


def save_bundle(bundle: RiskBundle, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, path)
    path.with_suffix(".json").write_text(json.dumps(bundle.metadata, indent=2))


def load_bundle(path: Path) -> RiskBundle:
    return joblib.load(path)


# ---------------------------------------------------------------------- runtime


class RiskEngine:
    """Stateful per-session assessor: keeps the feature history needed for CUSUM."""

    def __init__(self, bundle: RiskBundle) -> None:
        self.bundle = bundle
        self.history_t: list[float] = []
        self.history_X: list[np.ndarray] = []

    def assess(self, samples: Sequence[TelemetrySample]) -> RiskAssessment:
        start = time.perf_counter()
        t_now = samples[-1].t_s if samples else 0.0
        x = features_from_samples(samples)
        if x is None:
            return RiskAssessment(
                t_s=t_now,
                available=False,
                reason="Motor stopped or insufficient valid telemetry in the last 10 minutes",
                model_version=self.bundle.version,
            )
        if not self.history_t or t_now > self.history_t[-1]:
            self.history_t.append(t_now)
            self.history_X.append(x)
        b = self.bundle
        X = x.reshape(1, -1)

        horizons = [
            HorizonRisk(
                horizon_min=h,
                probability=float(b.risk_calibrated(X, h)[0]),
                raw_probability=float(b.risk_raw(X, h)[0]),
            )
            for h in b.horizons
        ]
        score = float(b.anomaly_scores(X)[0])
        anomaly = AnomalyResult(
            score=score, threshold=b.iforest_threshold, is_anomalous=score > b.iforest_threshold
        )
        diag = b.diagnosis_proba(X)[0]
        diagnosis = sorted(
            (
                DiagnosisProbability(label=lbl, probability=float(p))
                for lbl, p in zip(DIAGNOSIS_CLASSES, diag, strict=True)
            ),
            key=lambda d: d.probability,
            reverse=True,
        )

        hist = np.stack(self.history_X)
        change_points = []
        for name in CUSUM_SIGNALS:
            j = FEATURE_NAMES.index(name)
            drift, threshold = b.cusum_for(name)
            res = run_cusum(
                hist[:, j], float(b.healthy_mean[j]), float(b.healthy_std[j]), drift, threshold
            )
            change_points.append(
                ChangePoint(
                    signal=name,
                    detected=res.alarm_index is not None,
                    t_s=None if res.alarm_index is None else self.history_t[res.alarm_index],
                    direction=res.direction,
                    statistic=float(max(res.positive[-1], res.negative[-1])),
                )
            )

        z = b.zscores(X)[0]
        evidence = []
        for j, name in enumerate(FEATURE_NAMES):
            if name in ("missing_fraction", "speed_frac", "minutes_to_temp_limit"):
                continue
            evidence.append(
                EvidenceItem(
                    id=f"obs:{name}",
                    kind="observed",
                    signal=name,
                    value=round(float(x[j]), 4),
                    unit=EVIDENCE_UNITS.get(name, ""),
                    healthy_mean=round(float(b.healthy_mean[j]), 4),
                    z_score=round(float(z[j]), 2),
                    description=FEATURE_DESCRIPTIONS[name],
                )
            )
        evidence.sort(key=lambda e: abs(e.z_score or 0.0), reverse=True)
        for hr in horizons:
            evidence.append(
                EvidenceItem(
                    id=f"ml:risk_{hr.horizon_min}m",
                    kind="ml_prediction",
                    signal=f"failure_within_{hr.horizon_min}m",
                    value=round(hr.probability, 4),
                    description=f"Calibrated probability of failure within {hr.horizon_min} min",
                )
            )
        evidence.append(
            EvidenceItem(
                id="ml:anomaly",
                kind="ml_prediction",
                signal="isolation_forest_score",
                value=round(score, 4),
                description=f"Anomaly score (threshold {b.iforest_threshold:.3f})",
            )
        )
        evidence.append(
            EvidenceItem(
                id="ml:diagnosis",
                kind="ml_prediction",
                signal=f"diagnosis_{diagnosis[0].label}",
                value=round(diagnosis[0].probability, 4),
                description=f"Most likely active fault class: {diagnosis[0].label}",
            )
        )
        minutes_to_limit = float(x[FEATURE_NAMES.index("minutes_to_temp_limit")])
        return RiskAssessment(
            t_s=t_now,
            horizons=horizons,
            anomaly=anomaly,
            change_points=change_points,
            diagnosis=diagnosis,
            evidence=evidence,
            features={n: round(float(v), 4) for n, v in zip(FEATURE_NAMES, x, strict=True)},
            heuristic_minutes_to_temp_limit=None if minutes_to_limit >= 600 else minutes_to_limit,
            model_version=b.version,
            latency_ms=(time.perf_counter() - start) * 1000.0,
        )
