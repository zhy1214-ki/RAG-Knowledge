"""Clock evidence only: no database, container, credential or recovery operations."""
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path


SAFETY_CAP_NS = 60_000_000_000
FIELDS = ("sequence", "utc_start_ns", "utc_end_ns", "raw_utc_seconds",
    "monotonic_start_ns", "monotonic_end_ns", "wall_resolution_ns", "monotonic_resolution_ns")


class PreflightBlocked(RuntimeError):
    pass


def capture_sample(sequence, *, wall_ns, monotonic_ns, raw_wall,
                   wall_resolution_ns, monotonic_resolution_ns):
    """Each wall reading is inside the same integer monotonic bracket."""
    sample = {"sequence": sequence, "wall_resolution_ns": wall_resolution_ns,
        "monotonic_resolution_ns": monotonic_resolution_ns}
    try:
        sample["monotonic_start_ns"] = monotonic_ns()
        sample["utc_start_ns"] = wall_ns()
        sample["raw_utc_seconds"] = raw_wall()
        sample["utc_end_ns"] = wall_ns()
        sample["monotonic_end_ns"] = monotonic_ns()
    except Exception:
        sample["capture_failed"] = True  # Never retain exception text or arbitrary caller data.
    return sample


def _sanitize(samples):
    result = []
    for sample in samples if isinstance(samples, (tuple, list)) else []:
        safe = {}
        if isinstance(sample, dict):
            for key in FIELDS:
                value = sample.get(key)
                safe[key] = value if type(value) is int or (
                    type(value) is float and math.isfinite(value)) else None
            safe["capture_failed"] = sample.get("capture_failed") is True
        result.append(safe)
    return result


def _iso(ns):
    seconds, nanos = divmod(ns, 1_000_000_000)
    return datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + f".{nanos:09d}Z"


def _analyze(samples):
    value = {"stage": "SHORT_CLOCK_CONTINUITY", "status": "BLOCKED",
        "code": "R456_CLOCK_DATA_MISSING", "classification": "DATA_MISSING",
        "failed_condition": "TWO_VALID_ORDERED_SAMPLES_REQUIRED", "safety_cap_ns": SAFETY_CAP_NS,
        "wall_elapsed_ns": None, "monotonic_elapsed_bounds_ns": None,
        "resolution_allowance_ns": None, "residual_interval_ns": None, "allowed_residual_ns": 0}
    required = [key for key in FIELDS if key != "raw_utc_seconds"]
    if len(samples) != 2 or any(s.get("capture_failed") or any(
            type(s.get(k)) is not int or s[k] < 0 for k in required) or
            s["wall_resolution_ns"] == 0 or s["monotonic_resolution_ns"] == 0 for s in samples):
        return value
    a, b = samples
    if b["sequence"] <= a["sequence"]:
        return value
    try:
        value["utc_samples"] = [{"sequence": s["sequence"], "start": _iso(s["utc_start_ns"]),
            "end": _iso(s["utc_end_ns"])} for s in samples]
    except (ValueError, OverflowError, OSError):
        return value
    allowance = sum(s["wall_resolution_ns"] + s["monotonic_resolution_ns"] for s in samples)
    spans = [s["monotonic_end_ns"] - s["monotonic_start_ns"] for s in samples]
    wall_delta = b["utc_start_ns"] - a["utc_start_ns"]
    low = b["monotonic_start_ns"] - a["monotonic_end_ns"]
    high = b["monotonic_end_ns"] - a["monotonic_start_ns"]
    residual = [wall_delta - high - allowance, wall_delta - low + allowance]
    value.update(wall_elapsed_ns=wall_delta, monotonic_elapsed_bounds_ns=[low, high],
        resolution_allowance_ns=allowance, sample_spans_ns=spans, residual_interval_ns=residual,
        allowed_residual_ns=0, arithmetic="INTEGER_NANOSECONDS_NO_FLOAT_SUBTRACTION")
    value.update(code="R455_SHORT_CLOCK_CONTINUITY_FAILED", classification="CONTINUITY_ANOMALY")
    if any(span < 0 for span in spans) or low < 0:
        value["failed_condition"] = "MONOTONIC_ROLLBACK_OR_OVERLAPPING_SAMPLES"
    elif any(s["utc_end_ns"] < s["utc_start_ns"] for s in samples) or b["utc_start_ns"] < a["utc_end_ns"]:
        value["failed_condition"] = "UTC_ROLLBACK"
    elif max(spans) + allowance > SAFETY_CAP_NS:
        value.update(code="R456_CLOCK_PRECISION_INSUFFICIENT", classification="INSUFFICIENT_PRECISION",
            failed_condition="MEASURED_UNCERTAINTY_EXCEEDS_60_SECOND_CAP")
    elif any(s["utc_end_ns"] - s["utc_start_ns"] > span + allowance for s, span in zip(samples, spans)):
        value["failed_condition"] = "UTC_JUMP_WITHIN_SAMPLE"
    elif high == 0:
        value.update(code="R456_CLOCK_PRECISION_INSUFFICIENT", classification="INSUFFICIENT_PRECISION",
            failed_condition="NO_OBSERVABLE_ELAPSED_TIME")
    elif not residual[0] <= 0 <= residual[1]:
        value["failed_condition"] = "ELAPSED_INTERVALS_DISAGREE"
    elif max(abs(residual[0]), abs(residual[1])) > SAFETY_CAP_NS:
        value.update(code="R456_CLOCK_PRECISION_INSUFFICIENT", classification="INSUFFICIENT_PRECISION",
            failed_condition="RESIDUAL_UNCERTAINTY_EXCEEDS_60_SECOND_CAP")
    else:
        value.update(status="PASS", code="OK", classification="CONSISTENT_WITH_MEASURED_PRECISION",
            failed_condition=None)
    return value


def _durable_write(path, value):
    data = (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")
    with path.open("xb") as target:
        target.write(data)
        target.flush()
        os.fsync(target.fileno())
    if path.read_bytes() != data:
        raise OSError()
    return hashlib.sha256(data).hexdigest()


def check_pair(samples, output_dir):
    """Persist raw evidence and decision before returning PASS or raising a safe code."""
    directory = Path(output_dir)
    try:
        if any(parent.is_symlink() or (hasattr(parent, "is_junction") and parent.is_junction())
               for parent in (directory, *directory.parents)):
            raise OSError()
        directory.mkdir()  # Atomic claim; never delete/reuse a previous run.
    except FileExistsError:
        raise PreflightBlocked("R456_DIAGNOSTIC_OUTPUT_EXISTS") from None
    except OSError:
        raise PreflightBlocked("R456_DIAGNOSTIC_PERSISTENCE_FAILED") from None
    try:
        safe = _sanitize(samples)
        digest = _durable_write(directory / "samples.json", {
            "stage": "CAPTURED_BEFORE_EVALUATION", "samples": safe})
        decision = _analyze(safe)
        decision["samples_sha256"] = digest
        _durable_write(directory / "decision.json", decision)
    except (OSError, ValueError, TypeError, OverflowError):
        raise PreflightBlocked("R456_DIAGNOSTIC_PERSISTENCE_FAILED") from None
    if decision["status"] != "PASS":
        raise PreflightBlocked(decision["code"])
    return decision
