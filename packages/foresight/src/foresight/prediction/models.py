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

CUSUM_SIGNALS = ("rise_residual_k", "bearing_index", "load_frac")
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


def train_bundle(train: Dataset, validation: Dataset) -> RiskBundle:
    healthy = train.diagnosis == 0
    X_h = train.X[healthy]
    mean = X_h.mean(axis=0)
    std = X_h.std(axis=0) + 1e-6

    iforest = IsolationForest(n_estimators=200, contamination="auto", random_state=0)
    iforest.fit(X_h)
    val_healthy_scores = -iforest.score_samples(validation.X[validation.diagnosis == 0])
    iforest_threshold = float(np.quantile(val_healthy_scores, 0.995))

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

    fingerprint = hashlib.sha256(train.X.tobytes()).hexdigest()[:12]
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
            res = cusum(hist[:, j], float(b.healthy_mean[j]), float(b.healthy_std[j]))
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
