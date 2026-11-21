"""R4.5.5 dedicated epoch 1->2 rehearsal; fictional clocks and isolated SQLite only."""
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock
import json

import pytest
from sqlalchemy import select
from app.core.db import make_database
from app.core.errors import AppError
from app.real_usage.guard import GuardBase, GuardState, ModelCall, Operation, UsageGuard
import real_usage_runtime as runtime

FLOOR = 1795110533.7202606


class Clock:
    def __init__(self):
        self.wall = datetime(2026, 11, 20, 3, tzinfo=timezone.utc).timestamp()
        self.tick, self.delay = 1000.0, 0.000001

    def read_wall(self):
        value = self.wall
        self.wall += self.delay
        self.tick += self.delay
        return value

    def read_tick(self):
        return self.tick

    def advance(self, seconds, wall_seconds=None):
        self.tick += seconds
        self.wall += seconds if wall_seconds is None else wall_seconds


@pytest.fixture
def preview(settings, tmp_path, monkeypatch):
    cfg = settings.model_copy(update={"strict_clock_protection": True,
        "max_calls_total": 1000, "max_embedding_calls_total": 1000,
        "max_qwen_calls_total": 1000, "model_requests_per_minute": 5,
        "daily_budget_cny": Decimal("0.10"), "monthly_budget_cny": Decimal("3")})
    engine, sessions = make_database("sqlite:///" + (tmp_path / "fictional-r455.sqlite").as_posix())
    GuardBase.metadata.create_all(engine)
    with sessions() as db:
        db.add(GuardState(id=1, stopped=True, reason="CLOCK_REVIEW_REQUIRED",
            historical_requests=6, last_observed_at=FLOOR, clock_epoch=1))
        for index, cost in enumerate(["0.00005850", "0.00003800", "0.00134400", "0.00189200", "0.00181700"]):
            db.add(ModelCall(id=f"r455-synthetic-{index}", kind="embedding",
                created_at=FLOOR - 10 + index, day="2026-11-19", status="VERIFIED",
                estimated_input=8, reserved_output=0, input_tokens=1, output_tokens=0,
                charge_cny=Decimal(cost)))
            db.add(Operation(id=f"r455-synthetic-operation-{index}", fingerprint="f" * 64,
                created_at=FLOOR - 30 + index, status="SUCCESS"))
        db.commit()
    clock = Clock()
    guard = UsageGuard(engine, sessions, cfg, clock=clock.read_wall, monotonic=clock.read_tick)
    audit = cfg.audit_dir / "usage.jsonl"
    audit.write_text('{"event":"SYNTHETIC_CLOCK_REVIEW","epoch":1}\n', encoding="utf-8")
    monkeypatch.setattr(runtime, "database_url", lambda: "fictional-offline-only")
    monkeypatch.setattr("app.core.db.make_database", lambda _: (engine, sessions))
    monkeypatch.setattr(runtime, "Path", lambda value: audit if str(value) == "/audit/usage.jsonl" else Path(value))
    monkeypatch.setattr(runtime, "read_secret", Mock(side_effect=AssertionError("R455_SECRET_READ_FORBIDDEN")))
    monkeypatch.setattr(runtime, "load_settings", Mock(side_effect=AssertionError("R455_MODEL_SETUP_FORBIDDEN")))
    monkeypatch.setattr("time.time", clock.read_wall)
    monkeypatch.setattr("time.monotonic", clock.read_tick)
    yield guard, clock, engine, sessions, audit
    engine.dispose()


def ledger(sessions):
    with sessions() as db:
        return (
            [tuple(getattr(row, key) for key in ModelCall.__table__.columns.keys())
             for row in db.scalars(select(ModelCall).order_by(ModelCall.id))],
            [tuple(getattr(row, key) for key in Operation.__table__.columns.keys())
             for row in db.scalars(select(Operation).order_by(Operation.id))],
            db.get(GuardState, 1).historical_requests,
        )


def protected_check(guard, sessions):
    with guard.lock, sessions() as db:
        value = guard._checked_time(db, guard._state(db))
        db.commit()
        return value


@pytest.mark.parametrize("interval", [0.000001, 0.063, 0.066, 0.069])
def test_epoch1_to2_external_ack_first_anchor_and_following_samples(preview, interval, capsys):
    guard, clock, _, sessions, audit = preview
    before, old_audit = ledger(sessions), audit.read_bytes()
    assert guard.clock_epoch == 1
    with sessions() as db:
        assert db.get(GuardState, 1).stopped
    clock.delay = interval
    runtime.admin(True, True)  # Isolated fictional DB only; production is never connected.
    status = json.loads(capsys.readouterr().out)
    assert status["clock_epoch"] == 2 and not status["stopped"]
    assert guard.clock_epoch == 1
    protected_check(guard, sessions)
    anchor = (guard.wall_anchor, guard.monotonic_anchor, guard.monotonic_anchor_end)
    assert guard.clock_epoch == 2 and anchor[2] > anchor[1]
    high_water = []
    for _ in range(3):
        clock.advance(10)
        high_water.append(protected_check(guard, sessions))
    assert high_water == sorted(high_water) and high_water[-1] > high_water[0]
    assert (guard.wall_anchor, guard.monotonic_anchor, guard.monotonic_anchor_end) == anchor
    assert ledger(sessions) == before
    assert audit.read_bytes().startswith(old_audit)
    assert len(audit.read_text().splitlines()) == 2
    assert guard.summary()["cumulative_attempt_upper_bound"] == 11


@pytest.mark.parametrize("fault", ["wall_rollback", "monotonic_rollback", "fast_drift", "slow_drift"])
def test_real_fault_after_mock_epoch2_blocks_before_reservation_or_send(preview, fault):
    guard, clock, _, sessions, _ = preview
    runtime.admin(True, True)
    protected_check(guard, sessions)
    before = ledger(sessions)
    if fault == "wall_rollback":
        clock.wall -= 1
    elif fault == "monotonic_rollback":
        clock.tick -= 1
    else:
        clock.advance(120, 181 if fault == "fast_drift" else 59)
    send = Mock()
    with pytest.raises(AppError) as error:
        guard.execute("/embeddings", {"input": ["synthetic"]}, send, "EMBEDDING_ERROR")
    assert error.value.code == "USAGE_STOPPED"
    send.assert_not_called()
    assert ledger(sessions) == before
    with sessions() as db:
        state = db.get(GuardState, 1)
        assert state.stopped and state.reason == "CLOCK_REVIEW_REQUIRED" and state.clock_epoch == 2


def test_loading_or_restart_never_unlocks_historical_epoch1_pause(preview):
    guard, clock, engine, sessions, audit = preview
    before, old_audit = ledger(sessions), audit.read_bytes()
    restarted = UsageGuard(engine, sessions, guard.cfg, clock=clock.read_wall, monotonic=clock.read_tick)
    send = Mock()
    with pytest.raises(AppError) as error:
        restarted.execute("/embeddings", {"input": ["synthetic"]}, send, "EMBEDDING_ERROR")
    assert error.value.code == "USAGE_STOPPED"
    send.assert_not_called()
    with sessions() as db:
        state = db.get(GuardState, 1)
        assert state.stopped and state.clock_epoch == 1 and state.reason == "CLOCK_REVIEW_REQUIRED"
    assert ledger(sessions) == before and audit.read_bytes() == old_audit


def test_no_explicit_clock_confirmation_keeps_epoch1_ledger_and_audit(preview):
    _, _, _, sessions, audit = preview
    before, old_audit = ledger(sessions), audit.read_bytes()
    with pytest.raises(runtime.Stop, match="R4_EXPLICIT_CLOCK_ACK_REQUIRED"):
        runtime.admin(True, False)
    with sessions() as db:
        assert db.get(GuardState, 1).clock_epoch == 1 and db.get(GuardState, 1).stopped
    assert ledger(sessions) == before and audit.read_bytes() == old_audit


def test_clock_before_existing_checkpoint_cannot_confirm_epoch2(preview):
    _, clock, _, sessions, audit = preview
    before, old_audit = ledger(sessions), audit.read_bytes()
    clock.wall = FLOOR - 1
    with pytest.raises(runtime.Stop, match="R4_CLOCK_BEFORE_PERSISTED_RECORD"):
        runtime.admin(True, True)
    with sessions() as db:
        state = db.get(GuardState, 1)
        assert state.stopped and state.clock_epoch == 1 and state.last_observed_at == FLOOR
    assert ledger(sessions) == before and audit.read_bytes() == old_audit
