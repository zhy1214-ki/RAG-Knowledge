"""Offline-only review of sanitized evidence; no runtime, database or credential access."""
from datetime import datetime, timezone
import math


class ReviewBlocked(ValueError):
    pass


LIMITS = {
    "daily_budget_cny": "0.10", "monthly_budget_cny": "3",
    "max_calls_per_day": 60, "model_requests_per_minute": 5,
    "max_input_tokens": 4096, "max_output_tokens": 256,
    "max_calls_total": 1000, "max_embedding_calls_total": 1000,
    "max_qwen_calls_total": 1000, "strict_clock_protection": True,
    "model_timeout_seconds": 30, "max_document_chunks": 32,
    "max_upload_bytes": 20971520,
}
CONTROLS = {"maximum_concurrency": 1, "automatic_retries": 0}


def prepare_confirmation(evidence, *, accept_history_gap=False, accept_sync_gap=False):
    # These attestations must come from a separately reviewed, fresh read-only capture.
    # This function cannot verify a source, grant approval or execute a recovery.
    checks = (
        (accept_history_gap is True and accept_sync_gap is True, "R451_EXPLICIT_GAP_ACCEPTANCE_REQUIRED"),
        (all(evidence.get(k) is True for k in (
            "fresh_utc_reference_verified", "short_observation_verified",
            "identity_matches_approval", "ledger_matches_approved_snapshot",
            "pre_intent_durable", "exclusive_review_window")), "R451_EVIDENCE_INCOMPLETE"),
        (evidence.get("stopped") is True and evidence.get("reason") == "CLOCK_REVIEW_REQUIRED",
         "R451_PAUSE_STATE_MISMATCH"),
        (type(evidence.get("clock_epoch")) is int and evidence["clock_epoch"] == 0,
         "R451_EPOCH_MISMATCH"),
        (all(type(evidence.get(k)) is int and evidence[k] == 0 for k in
             ("unknown_calls", "sent_uncertain_calls", "running_operations")), "R451_REQUESTS_UNRESOLVED"),
        (evidence.get("historical_baseline") == 6 and evidence.get("model_rows") == 5,
         "R451_HISTORY_MISMATCH"),
        (evidence.get("limits") == LIMITS and evidence.get("controls") == CONTROLS,
         "R451_LIMITS_MISMATCH"),
    )
    for valid, code in checks:
        if not valid:
            raise ReviewBlocked(code)
    times = [evidence.get(k) for k in ("current_utc", "persisted_floor", "last_observed_at")]
    try:
        if not all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in times):
            raise ValueError()
        for value in times:
            datetime.fromtimestamp(value, timezone.utc)
        if not times[0] >= times[1] >= times[2]:
            raise ValueError()
    except (ValueError, TypeError, OverflowError, OSError):
        raise ReviewBlocked("R451_TIME_BOUNDS_INVALID") from None
    return {
        "decision": "CONDITIONAL_PLAN_ONLY", "execution_authorized": False,
        "expected_epoch_before": 0, "expected_epoch_after": 1,
        "historical_continuity": "NOT_VERIFIED", "windows_live_sync": "NOT_VERIFIED",
        "cumulative_model_calls_preserved": 11,
        "paid_test_calls_authorized": 0,
    }
