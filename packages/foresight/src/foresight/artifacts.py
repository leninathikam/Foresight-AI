"""Locations of generated artifacts (datasets, trained models, evaluation reports)."""

from __future__ import annotations

import os
from pathlib import Path

import joblib

REPO_ROOT = Path(__file__).resolve().parents[4]
ARTIFACTS_DIR = Path(os.environ.get("FORESIGHT_ARTIFACTS_DIR", REPO_ROOT / "artifacts"))
MODEL_PATH = ARTIFACTS_DIR / "models" / "risk_bundle.joblib"
DATASET_DIR = ARTIFACTS_DIR / "datasets"
REPORTS_DIR = ARTIFACTS_DIR / "reports"


def load_or_build_dataset(split: str, rebuild: bool = False):
    from foresight.prediction.dataset import build_dataset

    path = DATASET_DIR / f"{split}.joblib"
    if path.exists() and not rebuild:
        return joblib.load(path)
    ds = build_dataset(split)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(ds, path)
    return ds


def load_or_train_bundle(retrain: bool = False):
    from foresight.prediction.models import load_bundle, save_bundle, train_bundle

    if MODEL_PATH.exists() and not retrain:
        return load_bundle(MODEL_PATH)
    bundle = train_bundle(load_or_build_dataset("train"), load_or_build_dataset("validation"))
    save_bundle(bundle, MODEL_PATH)
    return bundle
