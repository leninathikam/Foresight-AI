"""Unit tests for CWRU bearing dataset loader, ISO 10816 preprocessor, and benchmark harness."""

from __future__ import annotations

import math

import numpy as np
import pytest

from foresight.artifacts import load_or_train_bundle
from foresight.evaluation.cwru import (
    DEFAULT_CWRU_PATH,
    CWRUDataset,
    compute_waveform_metrics,
    iso10816_velocity_rms,
    run_benchmark_episode,
)
from foresight.simulation import ScenarioId, canonical_episode
from foresight.telemetry import TelemetryStream


def test_iso10816_velocity_rms_theoretical_sine():
    """Verify ISO 10816 velocity RMS against exact analytical solution for a pure sine wave.

    For acceleration a(t) = A_g * g * sin(2*pi*f0*t):
      v(t) = - (A_g * g / (2*pi*f0)) * cos(2*pi*f0*t)
      v_rms_theoretical = 1000 * (A_g * 9.80665) / (2 * pi * f0 * sqrt(2)) mm/s
    """
    fs = 48000.0
    f0 = 100.0  # 100 Hz (well within ISO 10-1000 Hz band)
    a_g = 1.0  # 1 g amplitude
    t = np.arange(fs * 2.0) / fs  # 2 seconds
    sine_accel = a_g * np.sin(2.0 * np.pi * f0 * t)

    v_rms_calc = iso10816_velocity_rms(sine_accel, fs=fs, f_low=10.0, f_high=1000.0)
    v_rms_theoretical = 1000.0 * (a_g * 9.80665) / (2.0 * math.pi * f0 * math.sqrt(2.0))

    # Should match analytical integration within 1%
    assert abs(v_rms_calc - v_rms_theoretical) / v_rms_theoretical < 0.01


def test_iso10816_filters_out_of_band_frequencies():
    """Verify that frequencies below 10 Hz and above 1000 Hz are filtered out per ISO 10816."""
    fs = 48000.0
    t = np.arange(fs * 2.0) / fs
    # 5 Hz (below ISO band) and 5000 Hz (high-frequency sensor resonance)
    out_of_band = np.sin(2.0 * np.pi * 5.0 * t) + np.sin(2.0 * np.pi * 5000.0 * t)
    v_rms = iso10816_velocity_rms(out_of_band, fs=fs, f_low=10.0, f_high=1000.0)

    # In-band energy should be virtually zero (< 0.05 mm/s)
    assert v_rms < 0.05


def test_cwru_dataset_loading_and_integrity():
    """Verify CWRU dataset file exists, has correct checksum, 10 classes, and finite data."""
    if not DEFAULT_CWRU_PATH.exists():
        pytest.skip(f"CWRU dataset not found at {DEFAULT_CWRU_PATH}")

    ds = CWRUDataset(DEFAULT_CWRU_PATH)
    assert len(ds.sha256) == 64
    assert len(ds.classes) == 10
    assert "Normal" in ds.classes
    assert "IR_021" in ds.classes
    assert "OR_021" in ds.classes
    assert "Ball_021" in ds.classes

    for cond in ds.classes:
        segs = ds.get_segments(cond)
        assert len(segs) == 460
        assert segs.shape[1] == 1024
        assert np.all(np.isfinite(segs))


def test_compute_waveform_metrics():
    """Verify waveform statistics computation for normal vs severe defect."""
    if not DEFAULT_CWRU_PATH.exists():
        pytest.skip(f"CWRU dataset not found at {DEFAULT_CWRU_PATH}")

    ds = CWRUDataset(DEFAULT_CWRU_PATH)
    normal_seg = ds.get_segments("Normal")[0]
    or_seg = ds.get_segments("OR_021")[0]

    m_norm = compute_waveform_metrics(normal_seg, ds.sampling_rate_hz)
    m_or = compute_waveform_metrics(or_seg, ds.sampling_rate_hz)

    # Check required keys
    for k in ("accel_rms_g", "accel_peak_g", "crest_factor", "kurtosis", "velocity_rms_mm_s"):
        assert k in m_norm
        assert k in m_or

    # Defect segment must have higher peak acceleration and higher velocity RMS than normal
    assert m_or["accel_peak_g"] > m_norm["accel_peak_g"]
    assert m_or["velocity_rms_mm_s"] > m_norm["velocity_rms_mm_s"]
    assert m_or["crest_factor"] >= 1.0


def test_zero_shot_episode_benchmark_runs():
    """Verify zero-shot episode benchmark evaluation with RiskEngine."""
    if not DEFAULT_CWRU_PATH.exists():
        pytest.skip(f"CWRU dataset not found at {DEFAULT_CWRU_PATH}")

    bundle = load_or_train_bundle()
    ds = CWRUDataset(DEFAULT_CWRU_PATH)

    # Short 40-minute stream for test efficiency
    stream = TelemetryStream(canonical_episode(ScenarioId.HEALTHY, seed=1))
    stream.advance(40 * 60)
    base_samples = list(stream.window)

    res = run_benchmark_episode(
        bundle=bundle,
        dataset=ds,
        condition="Normal",
        base_samples=base_samples,
        scale=1.0,
        fault_onset_min=20.0,
    )

    assert res.condition == "Normal"
    assert res.false_alarm_rate == 0.0
    assert res.peak_vibration_mm_s > 0.0
    assert res.final_diagnosis in ("none", "bearing", "cooling", "overload")
