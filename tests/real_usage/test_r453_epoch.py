"""R4.5.3: external epoch adoption with measured, nonzero sampling intervals; offline only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from threading import Barrier
from unittest.mock import Mock
from pathlib import Path

import pytest
from sqlalchemy import select
from app.core.db import make_database
from app.core.errors import AppError
from app.real_usage.guard import GuardState, ModelCall, Operation, UsageGuard


class Clock:
    def __init__(self):
        self.wall = datetime(2027, 1, 15, 12, tzinfo=timezone.utc).timestamp()
        self.tick, self.delay = 1000.0, 0.000001

    def advance(self, seconds, wall_seconds=None):
        self.tick += seconds
        self.wall += seconds if wall_seconds is None else wall_seconds

    def read_wall(self):
        value = self.wall
        self.advance(self.delay)
        return value

    def read_tick(self):
        return self.tick


@pytest.fixture
def rig(settings, tmp_path):
    cfg = settings.model_copy(update={"strict_clock_protection": True,
        "max_calls_total": 1000, "max_embedding_calls_total": 1000,
        "max_qwen_calls_total": 1000, "model_requests_per_minute": 5,
        "daily_budget_cny": Decimal("0.10"), "monthly_budget_cny": Decimal("3")})
    engine, sessions = make_database("sqlite:///" + (tmp_path / "epoch.sqlite").as_posix())
    clock = Clock()
    guard = UsageGuard(engine, sessions, cfg, clock=clock.read_wall, monotonic=clock.read_tick)
    yield guard, clock, engine, sessions
    engine.dispose()


def external_epoch(rig, epoch=1):
    _, clock, _, sessions = rig
    with sessions() as db:
        row = db.get(GuardState, 1)
        row.clock_epoch = epoch
        row.last_observed_at = max(row.last_observed_at, clock.wall)
        db.commit()


def operation(guard, digest="synthetic"):
    identity = guard.begin_operation("synthetic-owner", "synthetic-kb", "upload", digest)
    guard.finish_operation(identity, True)


def seed_ledger(rig, unknown=False):
    _, clock, _, sessions = rig
    costs = ["0.00005850", "0.00003800", "0.00134400", "0.00189200", "0.00181700"]
    with sessions() as db:
        for index, cost in enumerate(costs):
            db.add(ModelCall(id=f"synthetic-{index}", kind="embedding",
                created_at=clock.wall - 10, day="2027-01-15",
                status="UNKNOWN" if unknown and index == 4 else "VERIFIED",
                estimated_input=8, reserved_output=0, input_tokens=1,
                output_tokens=0, charge_cny=Decimal(cost)))
        db.add(Operation(id="synthetic-old-operation", fingerprint="f" * 64,
            created_at=clock.wall - 10, status="FAILED"))
        db.commit()


def ledger(sessions):
    with sessions() as db:
        calls = [tuple(getattr(row, key) for key in ModelCall.__table__.columns.keys())
            for row in db.scalars(select(ModelCall).order_by(ModelCall.id))]
        operations = [tuple(getattr(row, key) for key in Operation.__table__.columns.keys())
            for row in db.scalars(select(Operation).order_by(Operation.id))]
        return calls, operations, db.get(GuardState, 1).historical_requests


def anchors(guard):
    return guard.wall_anchor, guard.monotonic_anchor, guard.monotonic_anchor_end, guard.clock_epoch


def denied(guard):
    send = Mock()
    with pytest.raises(AppError) as error:
        guard.execute("/embeddings", {"input": ["synthetic"]}, send, "EMBEDDING_ERROR")
    assert error.value.code == "USAGE_STOPPED"
    send.assert_not_called()


@pytest.mark.parametrize("interval", [0.000001, 0.063, 0.066, 0.069])
def test_external_epoch_nonzero_sample_is_adopted(rig, interval):
    guard, clock, _, sessions = rig
    clock.delay = interval
    external_epoch(rig)
    operation(guard)
    assert guard.clock_epoch == 1
    assert guard.monotonic_anchor_end > guard.monotonic_anchor
    with sessions() as db:
        row = db.get(GuardState, 1)
        assert not row.stopped and row.clock_epoch == 1


def test_following_samples_keep_anchor_and_continue_time_checks(rig):
    guard, clock, _, sessions = rig
    clock.delay = 0.066
    external_epoch(rig)
    operation(guard, "first")
    baseline = anchors(guard)
    high_water = []
    for index in range(5):
        clock.advance(10)
        operation(guard, str(index))
        with sessions() as db:
            high_water.append(db.get(GuardState, 1).last_observed_at)
    assert anchors(guard) == baseline
    assert high_water == sorted(high_water) and high_water[-1] > high_water[0]


def test_actual_external_admin_adopts_nonzero_sample_without_refund(rig, monkeypatch, capsys):
    import real_usage_runtime as runtime
    guard, clock, engine, sessions = rig
    seed_ledger(rig)
    guard.stop("CLOCK_REVIEW_REQUIRED")
    audit = guard.audit / "usage.jsonl"
    audit.write_text('{"event":"SYNTHETIC_CLOCK_PAUSE","epoch":0}\n', encoding="utf-8")
    old_audit, before = audit.read_bytes(), ledger(sessions)
    limits = guard.cfg.model_dump(include={"daily_budget_cny", "monthly_budget_cny",
        "max_calls_per_day", "model_requests_per_minute"})
    monkeypatch.setattr(runtime, "database_url", lambda: "fictional-sqlite-only")
    monkeypatch.setattr("app.core.db.make_database", lambda _: (engine, sessions))
    monkeypatch.setattr(runtime, "Path", lambda value: audit if str(value) == "/audit/usage.jsonl" else Path(value))
    monkeypatch.setattr(runtime, "read_secret", Mock(side_effect=AssertionError("NO_SECRET_READ")))
    monkeypatch.setattr(runtime, "load_settings", Mock(side_effect=AssertionError("NO_MODEL_SETUP")))
    monkeypatch.setattr("time.time", clock.read_wall)
    monkeypatch.setattr("time.monotonic", clock.read_tick)
    clock.delay = 0.000001
    runtime.admin(True, True)
    capsys.readouterr()
    assert guard.clock_epoch == 0
    with guard.lock, sessions() as db:
        guard._checked_time(db, guard._state(db))
        db.commit()
    assert guard.clock_epoch == 1 and ledger(sessions) == before
    assert audit.read_bytes().startswith(old_audit)
    assert guard.cfg.model_dump(include=set(limits)) == limits
    assert guard.summary()["cumulative_attempt_upper_bound"] == 11


@pytest.mark.parametrize("fault", ["wall_rollback", "monotonic_rollback", "fast_drift", "slow_drift"])
def test_real_fault_after_adoption_still_blocks_without_spending(rig, fault):
    guard, clock, _, sessions = rig
    external_epoch(rig)
    operation(guard)
    before = ledger(sessions)
    if fault == "wall_rollback":
        clock.wall -= 0.001
    elif fault == "monotonic_rollback":
        clock.tick -= 1
    else:
        clock.advance(120, 181 if fault == "fast_drift" else 59)
    denied(guard)
    with sessions() as db:
        assert db.get(GuardState, 1).reason == "CLOCK_REVIEW_REQUIRED"
    assert ledger(sessions) == before


@pytest.mark.parametrize("fault", ["future_checkpoint", "invalid_checkpoint", "invalid_epoch",
    "epoch_regression", "unbounded_sample", "invalid_monotonic", "future_ledger", "invalid_ledger"])
def test_invalid_candidate_does_not_replace_existing_anchor(rig, fault):
    guard, clock, _, sessions = rig
    if fault == "epoch_regression":
        external_epoch(rig)
        operation(guard)
    external_epoch(rig, 0 if fault == "epoch_regression" else 1)
    with sessions() as db:
        row = db.get(GuardState, 1)
        if fault == "future_checkpoint":
            row.last_observed_at = clock.wall + 100
        elif fault == "invalid_checkpoint":
            row.last_observed_at = -1
        elif fault == "invalid_epoch":
            row.clock_epoch = -1
        elif fault in {"future_ledger", "invalid_ledger"}:
            db.add(ModelCall(id="synthetic-invalid-time", kind="embedding",
                created_at=clock.wall + 100 if fault == "future_ledger" else -1,
                day="synthetic", status="VERIFIED", estimated_input=1, reserved_output=0,
                input_tokens=1, output_tokens=0, charge_cny=Decimal("0.001")))
        db.commit()
    if fault == "unbounded_sample":
        clock.delay = 61
    if fault == "invalid_monotonic":
        clock.tick = float("nan")
    previous_anchor, before = anchors(guard), ledger(sessions)
    denied(guard)
    assert anchors(guard) == previous_anchor
    assert ledger(sessions) == before
    with sessions() as db:
        assert db.get(GuardState, 1).stopped


@pytest.mark.parametrize("boundary", ["day", "month"])
def test_continuous_utc_rollover_after_adoption_preserves_lifetime(rig, boundary):
    guard, clock, _, sessions = rig
    clock.wall = datetime(2027, 1, 31 if boundary == "month" else 15, 23, 59, 50,
        tzinfo=timezone.utc).timestamp()
    seed_ledger(rig)
    external_epoch(rig)
    operation(guard, "before")
    before_calls = ledger(sessions)[0]
    clock.advance(20)
    operation(guard, "after")
    summary = guard.summary()
    assert summary["day_utc"] == ("2027-02-01" if boundary == "month" else "2027-01-16")
    assert summary["cumulative_attempt_upper_bound"] == 11
    assert Decimal(summary["monthly_reserved_cny"]) == (Decimal(0) if boundary == "month" else Decimal("0.00514950"))
    assert ledger(sessions)[0] == before_calls
    with sessions() as db:
        assert not db.get(GuardState, 1).stopped


@pytest.mark.parametrize("interval", [0.000001, 0.063, 0.066, 0.069])
def test_initial_and_restarted_anchor_with_nonzero_interval(rig, interval):
    guard, clock, engine, sessions = rig
    external_epoch(rig)
    operation(guard, "original")
    clock.delay = interval
    restarted = UsageGuard(engine, sessions, guard.cfg, clock=clock.read_wall, monotonic=clock.read_tick)
    operation(restarted, "same-day-restart")
    assert restarted.clock_epoch == 1 and not restarted.summary()["stopped"]


@pytest.mark.parametrize("boundary", ["day", "month"])
def test_cross_date_restart_keeps_clock_pause_and_unknown_reservation(rig, boundary):
    guard, clock, engine, sessions = rig
    seed_ledger(rig, unknown=True)
    external_epoch(rig)
    operation(guard, "before-restart")
    before = ledger(sessions)
    clock.advance(86400 if boundary == "day" else 32 * 86400)
    restarted = UsageGuard(engine, sessions, guard.cfg, clock=clock.read_wall, monotonic=clock.read_tick)
    denied(restarted)
    assert ledger(sessions) == before
    assert restarted.summary()["stopped"] and restarted.summary()["clock_epoch"] == 1
    assert Decimal(restarted.summary()["estimated_reserved_cny"]) == Decimal("0.00514950")


@pytest.mark.parametrize("reason", ["CLOCK_REVIEW_REQUIRED", "MODEL_OR_USAGE_UNCERTAIN", "MANUAL_PAUSE"])
def test_historical_pause_is_not_implicitly_cleared_by_new_epoch(rig, reason):
    guard, _, _, sessions = rig
    seed_ledger(rig, unknown=True)
    guard.stop(reason)
    external_epoch(rig)
    before_anchor, before = anchors(guard), ledger(sessions)
    denied(guard)
    assert anchors(guard) == before_anchor and ledger(sessions) == before
    with sessions() as db:
        row = db.get(GuardState, 1)
        assert row.stopped and row.reason == reason and row.clock_epoch == 1


@pytest.mark.parametrize("independent", [False, True])
def test_concurrent_adoption_is_serialized_and_does_not_double_start(rig, independent):
    guard, clock, engine, sessions = rig
    second = UsageGuard(engine, sessions, guard.cfg, clock=clock.read_wall, monotonic=clock.read_tick) if independent else guard
    external_epoch(rig)
    first_anchor = Mock(wraps=guard._anchor_clock)
    guard._anchor_clock = first_anchor
    second_anchor = None
    if independent:
        second_anchor = Mock(wraps=second._anchor_clock)
        second._anchor_clock = second_anchor
    barrier = Barrier(2)
    def attempt(item):
        worker, digest = item
        barrier.wait(timeout=5)
        try:
            return "OK", worker.begin_operation("synthetic", "kb", "upload", digest)
        except AppError as error:
            return error.code, None
    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(attempt, [(guard, "first"), (second, "second")]))
    assert sorted(code for code, _ in result) == ["OK", "USAGE_BUSY"]
    first_anchor.assert_called_once()
    if second_anchor:
        second_anchor.assert_called_once()
    assert guard.clock_epoch == second.clock_epoch == 1
    with sessions() as db:
        assert not db.get(GuardState, 1).stopped
    for code, identity in result:
        if code == "OK":
            guard.finish_operation(identity, True)


def test_first_model_boundary_reaches_one_mock_send_after_adoption(rig):
    guard, _, _, sessions = rig
    external_epoch(rig)
    send = Mock(return_value={"usage": {"prompt_tokens": 1}})
    guard.execute("/embeddings", {"input": ["synthetic"]}, send, "EMBEDDING_ERROR")
    send.assert_called_once()
    with sessions() as db:
        rows = db.scalars(select(ModelCall)).all()
        assert len(rows) == 1 and rows[0].status == "VERIFIED"
        assert guard.clock_epoch == 1


@pytest.mark.parametrize("kind", ["embedding", "qwen"])
def test_provider_boundary_still_blocks_real_fault_after_adoption(rig, kind):
    from app.real_usage.models import GuardedModels
    guard, clock, _, sessions = rig
    external_epoch(rig)
    operation(guard)
    clock.wall -= 1
    factory = Mock()
    models = GuardedModels(guard.cfg, guard, factory)
    with pytest.raises(AppError) as error:
        if kind == "embedding":
            models.embed(["synthetic"])
        else:
            models.answer("synthetic", [{"text": "synthetic", "source_id": 1}], [])
    assert error.value.code == "USAGE_STOPPED"
    factory.assert_not_called()


@pytest.mark.parametrize("budget", ["daily_budget_cny", "monthly_budget_cny"])
def test_adoption_keeps_exhausted_budget_and_ledger(rig, budget):
    guard, _, _, sessions = rig
    seed_ledger(rig)
    setattr(guard.cfg, budget, Decimal("0.00514950"))
    external_epoch(rig)
    before = ledger(sessions)
    send = Mock()
    with pytest.raises(AppError) as error:
        guard.execute("/embeddings", {"input": ["synthetic"]}, send, "EMBEDDING_ERROR")
    assert error.value.code == "USAGE_LIMIT" and guard.clock_epoch == 1
    send.assert_not_called()
    assert ledger(sessions) == before
