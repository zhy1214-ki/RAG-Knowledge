"""R4.5.1 protocol rehearsal only: fictional clocks, isolated SQLite, no live configuration."""
import copy
import hashlib
import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlalchemy import select
from app.core.db import make_database
from app.core.errors import AppError
from app.real_usage.guard import GuardState, ModelCall, Operation, UsageGuard
from clock_recovery_review import CONTROLS, LIMITS, ReviewBlocked, prepare_confirmation
import real_usage_runtime as runtime

NOW = 1800000000.0


@pytest.fixture
def evidence():
    return {
        **dict.fromkeys(("fresh_utc_reference_verified", "short_observation_verified",
            "identity_matches_approval", "ledger_matches_approved_snapshot",
            "pre_intent_durable", "exclusive_review_window"), True),
        "stopped": True, "reason": "CLOCK_REVIEW_REQUIRED", "clock_epoch": 0,
        "unknown_calls": 0, "sent_uncertain_calls": 0, "running_operations": 0,
        "historical_baseline": 6, "model_rows": 5,
        "current_utc": NOW, "persisted_floor": NOW - 1, "last_observed_at": NOW - 1,
        "limits": copy.deepcopy(LIMITS), "controls": dict(CONTROLS),
    }


def review(evidence):
    return prepare_confirmation(evidence, accept_history_gap=True, accept_sync_gap=True)


def test_ready_plan_preserves_unknown_history_and_grants_no_execution(evidence):
    before = copy.deepcopy(evidence)
    result = review(evidence)
    assert evidence == before
    assert result["expected_epoch_after"] == 1
    assert result["historical_continuity"] == result["windows_live_sync"] == "NOT_VERIFIED"
    assert result["execution_authorized"] is False and result["paid_test_calls_authorized"] == 0


@pytest.mark.parametrize("history,sync", [(False, False), (True, False), (False, True)])
def test_unknown_history_requires_both_explicit_acceptances(evidence, history, sync):
    with pytest.raises(ReviewBlocked, match="R451_EXPLICIT_GAP_ACCEPTANCE_REQUIRED"):
        prepare_confirmation(evidence, accept_history_gap=history, accept_sync_gap=sync)


@pytest.mark.parametrize("key,value,code", [
    ("fresh_utc_reference_verified", False, "EVIDENCE_INCOMPLETE"),
    ("short_observation_verified", False, "EVIDENCE_INCOMPLETE"),
    ("identity_matches_approval", False, "EVIDENCE_INCOMPLETE"),
    ("ledger_matches_approved_snapshot", False, "EVIDENCE_INCOMPLETE"),
    ("pre_intent_durable", False, "EVIDENCE_INCOMPLETE"),
    ("exclusive_review_window", False, "EVIDENCE_INCOMPLETE"),
    ("stopped", False, "PAUSE_STATE_MISMATCH"),
    ("reason", "MODEL_OR_USAGE_UNCERTAIN", "PAUSE_STATE_MISMATCH"),
    ("clock_epoch", 1, "EPOCH_MISMATCH"),
    ("unknown_calls", 1, "REQUESTS_UNRESOLVED"),
    ("sent_uncertain_calls", 1, "REQUESTS_UNRESOLVED"),
    ("running_operations", 1, "REQUESTS_UNRESOLVED"),
    ("model_rows", 0, "HISTORY_MISMATCH"),
    ("current_utc", NOW - 2, "TIME_BOUNDS_INVALID"),
    ("persisted_floor", float("nan"), "TIME_BOUNDS_INVALID"),
])
def test_preflight_rejections_never_invoke_admin(evidence, key, value, code):
    evidence[key] = value
    admin = Mock()
    with pytest.raises(ReviewBlocked, match="R451_" + code):
        review(evidence)
        admin()
    admin.assert_not_called()


@pytest.mark.parametrize("section,key,value", [
    ("limits", "daily_budget_cny", "1.00"),
    ("limits", "model_requests_per_minute", 60),
    ("limits", "strict_clock_protection", False),
    ("controls", "automatic_retries", 1),
])
def test_manual_confirmation_cannot_change_budget_or_safety_policy(evidence, section, key, value):
    evidence[section][key] = value
    with pytest.raises(ReviewBlocked, match="R451_LIMITS_MISMATCH"):
        review(evidence)


@pytest.fixture
def rig(settings, tmp_path, monkeypatch):
    cfg = settings.model_copy(update={**LIMITS, "daily_budget_cny": Decimal("0.10"),
        "monthly_budget_cny": Decimal("3"), "audit_dir": tmp_path / "audit"})
    engine, sessions = make_database("sqlite:///" + (tmp_path / "fictional.sqlite").as_posix())
    clock = [NOW, 1000.0]
    guard = UsageGuard(engine, sessions, cfg, clock=lambda: clock[0], monotonic=lambda: clock[1])
    costs = ["0.00005850", "0.00003800", "0.00134400", "0.00189200", "0.00181700"]
    with sessions() as db:
        for index, cost in enumerate(costs):
            db.add(ModelCall(id=f"synthetic-{index}", kind="embedding", created_at=NOW - 10,
                day="2027-01-15", status="VERIFIED", estimated_input=8, reserved_output=0,
                input_tokens=1, output_tokens=0, charge_cny=Decimal(cost)))
            db.add(Operation(id=f"synthetic-op-{index}", fingerprint="f" * 64,
                created_at=NOW - 10, status="SUCCESS"))
        state = db.get(GuardState, 1)
        state.stopped, state.reason = True, "CLOCK_REVIEW_REQUIRED"
        db.commit()
    audit = cfg.audit_dir / "usage.jsonl"
    audit.write_text('{"event":"SYNTHETIC_OLD_CLOCK_PAUSE","epoch":0}\n', encoding="utf-8")
    intent = tmp_path / "intent.json"
    with intent.open("x", encoding="utf-8") as target:
        json.dump({"reason_before": "CLOCK_REVIEW_REQUIRED", "epoch_before": 0,
            "historical_continuity": "NOT_VERIFIED", "windows_live_sync": "NOT_VERIFIED"}, target)
    monkeypatch.setattr(runtime, "database_url", lambda: "fictional-offline-only")
    monkeypatch.setattr("app.core.db.make_database", lambda _: (engine, sessions))
    monkeypatch.setattr(runtime, "Path", lambda name: audit if str(name) == "/audit/usage.jsonl" else Path(name))
    monkeypatch.setattr("time.time", lambda: clock[0])
    monkeypatch.setattr("time.monotonic", lambda: clock[1])
    monkeypatch.setattr(runtime, "read_secret", Mock(side_effect=AssertionError("OFFLINE_SECRET_READ_FORBIDDEN")))
    monkeypatch.setattr(runtime, "load_settings", Mock(side_effect=AssertionError("OFFLINE_CLIENT_SETUP_FORBIDDEN")))
    yield guard, clock, sessions, audit, intent
    engine.dispose()


def ledger(sessions):
    with sessions() as db:
        calls = [tuple(getattr(row, key) for key in ModelCall.__table__.columns.keys())
            for row in db.scalars(select(ModelCall).order_by(ModelCall.id))]
        operations = [tuple(getattr(row, key) for key in Operation.__table__.columns.keys())
            for row in db.scalars(select(Operation).order_by(Operation.id))]
        return calls, operations, db.get(GuardState, 1).historical_requests


def test_existing_admin_transition_keeps_ledger_prior_audit_and_budget(rig, evidence, capsys):
    guard, clock, sessions, audit, intent = rig
    before, old_audit, old_intent = ledger(sessions), audit.read_bytes(), intent.read_bytes()
    old_limits = guard.cfg.model_dump(include=set(LIMITS))
    assert review(evidence)["execution_authorized"] is False
    runtime.admin(True, True)  # Isolated SQLite only; a fictional separately authorized operator.
    status = json.loads(capsys.readouterr().out)
    assert status["clock_epoch"] == 1 and not status["stopped"]
    assert status["historical_baseline"] + status["r1_reserved_attempts"] == 11
    assert Decimal(status["reserved_estimate_cny"]) == Decimal("0.00514950")
    assert ledger(sessions) == before
    assert guard.cfg.model_dump(include=set(LIMITS)) == old_limits
    assert audit.read_bytes().startswith(old_audit) and intent.read_bytes() == old_intent
    assert json.loads(audit.read_text().splitlines()[-1])["clock_confirmed"] is True
    # Existing CLI affects DB epoch, not the in-process anchor. First protected check adopts it.
    assert guard.clock_epoch == 0
    with sessions() as db:
        state = guard._state(db)
        guard._checked_time(db, state)
        db.commit()
    assert guard.clock_epoch == 1 and ledger(sessions) == before


def test_missing_explicit_clock_ack_keeps_pause_and_all_evidence(rig):
    _, _, sessions, audit, intent = rig
    before, files = ledger(sessions), (audit.read_bytes(), intent.read_bytes())
    with pytest.raises(runtime.Stop, match="R4_EXPLICIT_CLOCK_ACK_REQUIRED"):
        runtime.admin(True, False)
    with sessions() as db:
        assert db.get(GuardState, 1).stopped and db.get(GuardState, 1).clock_epoch == 0
    assert ledger(sessions) == before and (audit.read_bytes(), intent.read_bytes()) == files


def test_audit_failure_after_commit_requires_readback_not_retry(rig, monkeypatch):
    _, _, sessions, audit, intent = rig
    before, old_intent = ledger(sessions), intent.read_bytes()
    sink = Mock()
    sink.open.side_effect = OSError("OFFLINE_SYNTHETIC_AUDIT_FAILURE")
    monkeypatch.setattr(runtime, "Path", lambda _: sink)
    with pytest.raises(OSError, match="OFFLINE_SYNTHETIC_AUDIT_FAILURE"):
        runtime.admin(True, True)
    sink.open.assert_called_once()
    # Confirmed actual behavior: a file error does NOT mean the DB transaction rolled back.
    with sessions() as db:
        state = db.get(GuardState, 1)
        assert not state.stopped and state.clock_epoch == 1
    assert ledger(sessions) == before and intent.read_bytes() == old_intent
    assert len(audit.read_text().splitlines()) == 1


def test_existing_intent_cannot_be_overwritten_or_trigger_confirmation(rig):
    _, _, sessions, _, intent = rig
    digest = hashlib.sha256(intent.read_bytes()).hexdigest()
    with pytest.raises(FileExistsError):
        with intent.open("x", encoding="utf-8") as target:
            target.write("must not overwrite")
        runtime.admin(True, True)
    assert hashlib.sha256(intent.read_bytes()).hexdigest() == digest
    with sessions() as db:
        assert db.get(GuardState, 1).stopped and db.get(GuardState, 1).clock_epoch == 0


@pytest.mark.parametrize("budget", ["daily_budget_cny", "monthly_budget_cny"])
def test_confirmation_does_not_refund_or_bypass_exhausted_budget(rig, budget):
    guard, _, sessions, _, _ = rig
    setattr(guard.cfg, budget, Decimal("0.00514950"))  # Fictional exhaustion, never a live config.
    before = ledger(sessions)
    runtime.admin(True, True)
    send = Mock()
    with pytest.raises(AppError) as error:
        guard.execute("/embeddings", {"input": ["synthetic"]}, send, "EMBEDDING_ERROR")
    assert error.value.code == "USAGE_LIMIT"
    send.assert_not_called()
    assert ledger(sessions) == before

@pytest.mark.parametrize("fault", ["wall_rollback", "large_drift", "cross_day_restart"])
def test_new_epoch_still_rejects_later_clock_faults_without_spending(rig, fault):
    guard, clock, sessions, _, _ = rig
    runtime.admin(True, True)
    with sessions() as db:
        guard._checked_time(db, guard._state(db))
        db.commit()
    before = ledger(sessions)
    if fault == "wall_rollback":
        clock[0] -= 0.001
    elif fault == "large_drift":
        clock[0] += 120
        clock[1] += 1
    else:
        clock[0] += 86400
        clock[1] += 86400
        # A new process cannot silently carry a trusted epoch across a UTC day.
        engine = sessions.kw["bind"]
        guard = UsageGuard(engine, sessions, guard.cfg, clock=lambda: clock[0], monotonic=lambda: clock[1])
    send = Mock()
    with pytest.raises(AppError) as error:
        guard.execute("/embeddings", {"input": ["synthetic"]}, send, "EMBEDDING_ERROR")
    assert error.value.code == "USAGE_STOPPED"
    send.assert_not_called()
    with sessions() as db:
        state = db.get(GuardState, 1)
        assert state.stopped and state.reason == "CLOCK_REVIEW_REQUIRED" and state.clock_epoch == 1
    assert ledger(sessions) == before
