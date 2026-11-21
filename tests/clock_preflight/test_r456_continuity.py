"""Pure virtual clocks and temporary diagnostic files; no live services."""
import hashlib
import json
import math
from pathlib import Path
import socket
import subprocess
import sys
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import clock_continuity_preflight as preflight

WALL = 1_795_143_888_000_000_000
TICK = 901_000_000_000_000


@pytest.fixture(autouse=True)
def no_external_operations(monkeypatch):
    denied = Mock(side_effect=AssertionError("R456_OFFLINE_EXTERNAL_OPERATION_FORBIDDEN"))
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(subprocess, "run", denied)


def sample(sequence, tick, wall, span=0, wall_end=None, resolution=1):
    return {"sequence": sequence, "utc_start_ns": wall,
        "utc_end_ns": wall if wall_end is None else wall_end,
        "raw_utc_seconds": wall / 1_000_000_000,
        "monotonic_start_ns": tick, "monotonic_end_ns": tick + span,
        "wall_resolution_ns": resolution, "monotonic_resolution_ns": resolution}


def read_decision(folder):
    return json.loads((folder / "decision.json").read_text())


def blocked(samples, folder, code):
    with pytest.raises(preflight.PreflightBlocked, match=code):
        preflight.check_pair(samples, folder)
    return read_decision(folder)


@pytest.mark.parametrize("span", [0, 1000, 1_000_000, 63_000_000, 66_000_000, 69_000_000])
def test_normal_integer_samples_and_nonzero_sampling_intervals(tmp_path, span):
    a = sample(0, TICK, WALL, span)
    b = sample(1, TICK + 2_000_000_000, WALL + 2_000_000_000, span)
    result = preflight.check_pair([a, b], tmp_path / "check")
    assert result["status"] == "PASS" and result["safety_cap_ns"] == 60_000_000_000
    assert result["wall_elapsed_ns"] == 2_000_000_000


def test_legacy_float_comparison_rejects_a_physically_continuous_one_microsecond_bracket(tmp_path):
    # a reads wall at its bracket end; b reads wall at its bracket start.
    a = sample(0, TICK, WALL, 1000)
    b = sample(1, TICK + 1_000_000, WALL + 999_000, 1000)
    wall = b["raw_utc_seconds"] - a["raw_utc_seconds"]
    low = b["monotonic_start_ns"] / 1e9 - a["monotonic_end_ns"] / 1e9
    high = b["monotonic_end_ns"] / 1e9 - a["monotonic_start_ns"] / 1e9
    legacy_interval = [wall - high - 4e-9, wall - low + 4e-9]
    assert math.ulp(a["raw_utc_seconds"]) > 200e-9
    assert legacy_interval[1] < 0  # Old reconstructed arithmetic deterministically rejects.
    result = preflight.check_pair([a, b], tmp_path / "integer-check")
    assert result["status"] == "PASS"
    assert result["wall_elapsed_ns"] == result["monotonic_elapsed_bounds_ns"][0] == 999_000


def test_capture_orders_all_readings_inside_integer_monotonic_bracket():
    order = []
    def reader(name, values):
        it = iter(values)
        def read():
            order.append(name)
            return next(it)
        return read
    result = preflight.capture_sample(3, wall_ns=reader("utc", [WALL, WALL + 100]),
        monotonic_ns=reader("mono", [TICK, TICK + 1000]), raw_wall=reader("float", [WALL / 1e9]),
        wall_resolution_ns=1, monotonic_resolution_ns=1)
    assert order == ["mono", "utc", "float", "utc", "mono"]
    assert result["monotonic_end_ns"] - result["monotonic_start_ns"] == 1000
    assert result["utc_start_ns"] == WALL and result["utc_end_ns"] == WALL + 100


@pytest.mark.parametrize("shift, expected", [(-4, "PASS"), (4, "PASS"), (-5, "BLOCKED"), (5, "BLOCKED")])
def test_reported_resolution_boundary_is_inclusive_without_extra_tolerance(tmp_path, shift, expected):
    samples = [sample(0, TICK, WALL), sample(1, TICK + 1_000_000, WALL + 1_000_000 + shift)]
    folder = tmp_path / "boundary"
    if expected == "PASS":
        result = preflight.check_pair(samples, folder)
    else:
        result = blocked(samples, folder, "R455_SHORT_CLOCK_CONTINUITY_FAILED")
    assert result["status"] == expected and result["resolution_allowance_ns"] == 4
    assert result["allowed_residual_ns"] == 0


@pytest.mark.parametrize("fault", ["utc_rollback", "mono_rollback", "fast_drift", "slow_drift", "within_sample_jump"])
def test_real_continuity_faults_still_block_and_are_recorded(tmp_path, fault):
    a = sample(0, TICK, WALL)
    b = sample(1, TICK + 120_000_000_000, WALL + 120_000_000_000)
    if fault == "utc_rollback":
        b["utc_start_ns"] = b["utc_end_ns"] = WALL - 1
    elif fault == "mono_rollback":
        b["monotonic_start_ns"] = b["monotonic_end_ns"] = TICK - 1
    elif fault == "within_sample_jump":
        b["utc_end_ns"] += 1_000_000_000
    else:
        shift = 61_000_000_000 if fault == "fast_drift" else -61_000_000_000
        b["utc_start_ns"] += shift
        b["utc_end_ns"] += shift
    folder = tmp_path / fault
    result = blocked([a, b], folder, "R455_SHORT_CLOCK_CONTINUITY_FAILED")
    assert result["classification"] == "CONTINUITY_ANOMALY" and result["failed_condition"]
    assert result["safety_cap_ns"] == 60_000_000_000
    assert (folder / "samples.json").exists()


def test_equal_values_are_insufficient_observation_not_fake_rollback(tmp_path):
    result = blocked([sample(0, TICK, WALL), sample(1, TICK, WALL)], tmp_path / "equal",
        "R456_CLOCK_PRECISION_INSUFFICIENT")
    assert result["failed_condition"] == "NO_OBSERVABLE_ELAPSED_TIME"


def test_scheduler_delay_is_measured_but_not_an_unbounded_allowance(tmp_path):
    a = sample(0, TICK, WALL, 2_000_000_000, WALL + 2_000_000_000)
    b = sample(1, TICK + 3_000_000_000, WALL + 3_000_000_000, 1_000_000_000)
    assert preflight.check_pair([a, b], tmp_path / "delayed")["status"] == "PASS"
    a["monotonic_end_ns"] = TICK + 60_000_000_000
    b["monotonic_start_ns"] = b["monotonic_end_ns"] = TICK + 61_000_000_000
    b["utc_start_ns"] = b["utc_end_ns"] = WALL + 61_000_000_000
    result = blocked([a, b], tmp_path / "too-wide", "R456_CLOCK_PRECISION_INSUFFICIENT")
    assert result["failed_condition"] == "MEASURED_UNCERTAINTY_EXCEEDS_60_SECOND_CAP"


def test_raw_evidence_is_durable_before_any_continuity_decision(tmp_path, monkeypatch):
    samples = [sample(0, TICK, WALL), sample(1, TICK + 1000, WALL - 1)]
    original = preflight._analyze
    folder = tmp_path / "retained"
    def inspect_persisted(values):
        raw = folder / "samples.json"
        assert json.loads(raw.read_text())["stage"] == "CAPTURED_BEFORE_EVALUATION"
        assert not (folder / "decision.json").exists()
        return original(values)
    monkeypatch.setattr(preflight, "_analyze", inspect_persisted)
    decision = blocked(samples, folder, "R455_SHORT_CLOCK_CONTINUITY_FAILED")
    assert decision["samples_sha256"] == hashlib.sha256((folder / "samples.json").read_bytes()).hexdigest()
    assert decision["wall_elapsed_ns"] == -1


@pytest.mark.parametrize("fail_at", [1, 2])
def test_diagnostic_fsync_failure_is_fatal_even_for_an_otherwise_valid_pair(tmp_path, monkeypatch, fail_at):
    original = preflight.os.fsync
    calls = []
    def fsync(fd):
        calls.append(fd)
        if len(calls) == fail_at:
            raise OSError("synthetic-sensitive-text-must-not-escape")
        original(fd)
    monkeypatch.setattr(preflight.os, "fsync", fsync)
    with pytest.raises(preflight.PreflightBlocked) as error:
        preflight.check_pair([sample(0, TICK, WALL), sample(1, TICK + 1000, WALL + 1000)], tmp_path / "fsync")
    assert str(error.value) == "R456_DIAGNOSTIC_PERSISTENCE_FAILED"
    assert len(calls) == fail_at
    if fail_at == 2:
        assert (tmp_path / "fsync/samples.json").exists()


def test_repeated_execution_cannot_overwrite_evidence_or_invoke_external_operations(tmp_path):
    folder = tmp_path / "once"
    pair = [sample(0, TICK, WALL), sample(1, TICK + 1000, WALL + 1000)]
    preflight.check_pair(pair, folder)
    old = {p.name: p.read_bytes() for p in folder.iterdir()}
    with pytest.raises(preflight.PreflightBlocked, match="R456_DIAGNOSTIC_OUTPUT_EXISTS"):
        preflight.check_pair(pair, folder)
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == old


@pytest.mark.parametrize("fault", ["missing", "same_sequence", "capture_failed", "wrong_type"])
def test_missing_or_unusable_data_is_retained_without_sensitive_fields(tmp_path, fault):
    a, b = sample(0, TICK, WALL), sample(1, TICK + 1000, WALL + 1000)
    b["unrelated_secret"] = "must-not-be-persisted"
    if fault == "missing":
        del b["monotonic_end_ns"]
    elif fault == "same_sequence":
        b["sequence"] = 0
    elif fault == "capture_failed":
        b["capture_failed"] = True
    else:
        b["utc_start_ns"] = "must-not-be-persisted"
    folder = tmp_path / fault
    result = blocked([a, b], folder, "R456_CLOCK_DATA_MISSING")
    assert result["classification"] == "DATA_MISSING"
    assert result["wall_elapsed_ns"] is None and result["allowed_residual_ns"] == 0
    assert "must-not-be-persisted" not in (folder / "samples.json").read_text()


def test_sampling_exception_becomes_missing_data_not_a_leaked_exception(tmp_path):
    failing = Mock(side_effect=RuntimeError("must-not-be-persisted"))
    b = preflight.capture_sample(1, wall_ns=failing, monotonic_ns=lambda: TICK + 1000,
        raw_wall=lambda: 0.0, wall_resolution_ns=1, monotonic_resolution_ns=1)
    folder = tmp_path / "sampling-failure"
    result = blocked([sample(0, TICK, WALL), b], folder, "R456_CLOCK_DATA_MISSING")
    assert result["classification"] == "DATA_MISSING"
    assert result["wall_elapsed_ns"] is None and result["allowed_residual_ns"] == 0
    assert "must-not-be-persisted" not in (folder / "samples.json").read_text()


@pytest.mark.parametrize("wall_delta", [0, 15_625_000])
def test_reported_windows_tick_resolution_is_used_without_fixed_extra_margin(tmp_path, wall_delta):
    samples = [sample(0, TICK, WALL, resolution=15_625_000),
        sample(1, TICK + 15_625_000, WALL + wall_delta, resolution=15_625_000)]
    result = preflight.check_pair(samples, tmp_path / "coarse-tick")
    assert result["status"] == "PASS"
    assert result["resolution_allowance_ns"] == 62_500_000


def test_raw_float_quantization_is_retained_but_does_not_replace_integer_clock(tmp_path):
    a = sample(0, TICK, WALL)
    b = sample(1, TICK + 1, WALL + 1)
    assert a["raw_utc_seconds"] == b["raw_utc_seconds"]
    folder = tmp_path / "integer-ns"
    result = preflight.check_pair([a, b], folder)
    raw = json.loads((folder / "samples.json").read_text())
    assert result["wall_elapsed_ns"] == 1
    assert raw["samples"][1]["utc_start_ns"] - raw["samples"][0]["utc_start_ns"] == 1
