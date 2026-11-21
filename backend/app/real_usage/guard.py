"""Persistent local safeguards; only the isolated real environment creates these tables."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import hmac
import json
import math
from pathlib import Path
from threading import Lock, RLock
import time
from uuid import uuid4
from sqlalchemy import Boolean, Float, Integer, Numeric, String, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from app.core.errors import AppError


class GuardBase(DeclarativeBase):
    pass


class GuardState(GuardBase):
    __tablename__ = "real_usage_guard"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stopped: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str] = mapped_column(String(64), default="")
    historical_requests: Mapped[int] = mapped_column(Integer, default=6)
    last_observed_at: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    clock_epoch: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class ModelCall(GuardBase):
    __tablename__ = "real_usage_calls"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[float] = mapped_column(Float, index=True)
    day: Mapped[str] = mapped_column(String(10), index=True)
    status: Mapped[str] = mapped_column(String(24))
    estimated_input: Mapped[int] = mapped_column(Integer)
    reserved_output: Mapped[int] = mapped_column(Integer)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    charge_cny: Mapped[Decimal] = mapped_column(Numeric(18, 8))


class Operation(GuardBase):
    __tablename__ = "real_usage_operations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16))


def usage_windows(now):
    current = datetime.fromtimestamp(now, timezone.utc)
    day = current.replace(hour=0, minute=0, second=0, microsecond=0)
    month = day.replace(day=1)
    following = month.replace(year=month.year + 1, month=1) if month.month == 12 else month.replace(month=month.month + 1)
    return {"day": day.date().isoformat(), "month": month.strftime("%Y-%m"),
        "day_start": day.timestamp(), "day_end": (day + timedelta(days=1)).timestamp(),
        "month_start": month.timestamp(), "month_end": following.timestamp()}


def blocked(code, status=429):
    raise AppError(code, {
        "USAGE_STOPPED": "模型调用已暂停，请先核对用量和失败记录。",
        "USAGE_LIMIT": "模型请求次数或估算预算已达本环境上限。",
        "USAGE_RATE_LIMIT": "模型请求过于频繁，请稍后操作，不要重复提交。",
        "USAGE_BUSY": "已有处理任务进行中，请等待当前任务完成。",
        "DUPLICATE_REQUEST": "近期已提交相同内容，请先查看处理状态或会话记录。",
        "TOKEN_LIMIT": "本次输入超过环境Token估算上限，请缩小文档或上下文。",
        "USAGE_STORAGE": "用量记录不可用，已安全阻断模型调用。",
    }.get(code, "模型保护检查未通过。"), status)


def sample_clock(clock, monotonic):
    # The wall reading happened somewhere inside this measured monotonic interval.
    before = monotonic()
    wall = clock()
    return wall, before, monotonic()


def valid_clock_sample(sample):
    if not all(isinstance(v, (int, float)) and math.isfinite(v) and v >= 0 for v in sample):
        return False
    try:
        datetime.fromtimestamp(sample[0], timezone.utc)
    except (ValueError, OverflowError, OSError):
        return False
    return sample[1] <= sample[2]


def persisted_time_floor(db, state):
    values = [state.last_observed_at]
    for model in (ModelCall, Operation):
        values.extend(v if v is not None else 0 for v in db.execute(
            select(func.min(model.created_at), func.max(model.created_at))).one())
    if type(state.clock_epoch) is not int or state.clock_epoch < 0:
        return None
    for value in values:
        if not valid_clock_sample((value, 0, 0)):
            return None
    return max(values)


class UsageGuard:
    def __init__(self, engine, sessions, settings, clock=time.time, monotonic=time.monotonic):
        self.sessions, self.cfg, self.clock = sessions, settings, clock
        self.dialect, self.monotonic = engine.dialect.name, monotonic
        initial_sample = sample_clock(self.clock, self.monotonic)
        self.lock, self.call_lock = RLock(), Lock()
        self.audit = Path(settings.audit_dir)
        if self.audit.is_symlink() or (hasattr(self.audit, "is_junction") and self.audit.is_junction()):
            blocked("USAGE_STORAGE", 503)
        self.audit.mkdir(parents=True, exist_ok=True)
        GuardBase.metadata.create_all(engine)
        with sessions() as db:
            state = self._state(db)
            if state is None:
                state = GuardState(id=1, historical_requests=6, last_observed_at=0, clock_epoch=0); db.add(state)
            if state.historical_requests != 6:
                blocked("USAGE_STORAGE", 503)
            calls = db.scalars(select(ModelCall).where(ModelCall.status == "SENT_UNCERTAIN")).all()
            operations = db.scalars(select(Operation).where(Operation.status == "RUNNING")).all()
            if calls or operations:
                state.stopped, state.reason = True, "PROCESS_INTERRUPTED"
                for row in calls: row.status = "UNKNOWN"
                for row in operations: row.status = "FAILED"
            floor = persisted_time_floor(db, state)
            now = initial_sample[0]
            invalid = floor is None or not valid_clock_sample(initial_sample)
            if invalid or (settings.strict_clock_protection and floor and (
                    now < floor or usage_windows(now)["day"] != usage_windows(floor)["day"])):
                state.stopped, state.reason = True, "CLOCK_REVIEW_REQUIRED"
                # Never replace an untrusted checkpoint with the current clock.
                if floor is not None:
                    state.last_observed_at = floor
            else:
                state.last_observed_at = max(floor, now)
            self._anchor_clock(initial_sample, state.clock_epoch)
            db.commit()

    def _state(self, db):
        # Serialize reservations in the database, including independent guard instances.
        if self.dialect == "sqlite":
            db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        return db.scalar(select(GuardState).where(GuardState.id == 1).with_for_update())

    def _anchor_clock(self, sample, epoch):
        self.wall_anchor, self.monotonic_anchor, self.monotonic_anchor_end = sample
        self.last_wall_reading, self.last_tick = sample[0], sample[2]
        self.clock_epoch = epoch

    def _projected_bounds(self, sample, anchor=None):
        wall, before, after = sample
        wall_anchor, monotonic_anchor, monotonic_anchor_end = anchor if anchor is not None else (
            self.wall_anchor, self.monotonic_anchor, self.monotonic_anchor_end)
        low = math.fsum((wall_anchor, before, -monotonic_anchor_end))
        high = math.fsum((wall_anchor, after, -monotonic_anchor))
        # Only measured sampling intervals and floating-point precision widen the bounds.
        error = sum(math.ulp(v) for v in (wall, wall_anchor, before, after,
            monotonic_anchor, monotonic_anchor_end, low, high))
        return low, high, error

    def _clock_consistent(self, sample, *, new_anchor=False):
        if not valid_clock_sample(sample):
            return False
        if not new_anchor and (sample[0] < self.last_wall_reading or sample[1] < self.last_tick):
            return False
        low, high, error = self._projected_bounds(sample, sample if new_anchor else None)
        # Keep the existing 60-second drift limit; uncertain measurements fail closed.
        return sample[0] - low + error <= 60 and high - sample[0] + error <= 60

    def _checked_time(self, db, state):
        sample = sample_clock(self.clock, self.monotonic)
        if self.cfg.strict_clock_protection:
            checkpoint_valid = valid_clock_sample((state.last_observed_at, 0, 0)) and type(state.clock_epoch) is int and state.clock_epoch >= 0
            new_epoch = state.clock_epoch != self.clock_epoch
            if new_epoch:
                floor = persisted_time_floor(db, state)
                checkpoint_valid = (checkpoint_valid and not state.stopped and state.clock_epoch > self.clock_epoch
                    and floor is not None and valid_clock_sample(sample) and sample[0] >= floor)
            if not checkpoint_valid or not self._clock_consistent(sample, new_anchor=new_epoch):
                state.stopped, state.reason = True, "CLOCK_REVIEW_REQUIRED"
                db.commit()
                blocked("USAGE_STOPPED", 503)
            if new_epoch:
                # Validate the candidate before replacing the live anchor; compare only later samples.
                self._anchor_clock(sample, state.clock_epoch)
                state.last_observed_at = max(state.last_observed_at, floor)
            self.last_wall_reading, self.last_tick = sample[0], sample[2]
            # Bill from the conservative monotonic projection, never from a wall adjustment.
            now = self._projected_bounds(sample)[0]
        else:
            now = sample[0]
        state.last_observed_at = max(state.last_observed_at, now)
        return state.last_observed_at

    def _audit(self, event, **values):
        try:
            target = self.audit / "usage.jsonl"
            if target.is_symlink(): raise ValueError()
            with target.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"time": self.clock(), "event": event, **values}) + "\n")
        except Exception:
            self.stop("AUDIT_WRITE_FAILED")
            blocked("USAGE_STORAGE", 503)

    def stop(self, reason):
        with self.lock, self.sessions() as db:
            row = self._state(db)
            row.stopped, row.reason = True, reason
            db.commit()

    def acknowledge_stop(self, acknowledge_clock=False):
        # Operator-only action: keeps reservations, request counts and duplicate history.
        with self.lock, self.sessions() as db:
            row = self._state(db)
            if db.scalar(select(Operation.id).where(Operation.status == "RUNNING").limit(1)):
                blocked("USAGE_BUSY")
            if db.scalar(select(ModelCall.id).where(ModelCall.status == "SENT_UNCERTAIN").limit(1)):
                blocked("USAGE_BUSY")
            if row.reason == "CLOCK_REVIEW_REQUIRED" and not acknowledge_clock:
                blocked("USAGE_STOPPED", 503)
            if acknowledge_clock:
                sample = sample_clock(self.clock, self.monotonic)
                floor = persisted_time_floor(db, row)
                if floor is None or not valid_clock_sample(sample) or sample[0] < floor:
                    blocked("USAGE_STOPPED", 503)
                row.last_observed_at, row.clock_epoch = max(floor, sample[0]), row.clock_epoch + 1
                self._anchor_clock(sample, row.clock_epoch)
            row.stopped, row.reason = False, ""
            db.commit()
        self._audit("OPERATOR_ACKNOWLEDGED", clock_confirmed=acknowledge_clock)

    def begin_operation(self, owner, scope, kind, digest):
        fingerprint = hmac.new(self.cfg.jwt_secret.get_secret_value().encode(),
            json.dumps([owner, scope, kind, digest]).encode(), hashlib.sha256).hexdigest()
        with self.lock, self.sessions() as db:
            state = self._state(db)
            if state.stopped: blocked("USAGE_STOPPED", 503)
            now = self._checked_time(db, state)
            if db.scalar(select(Operation.id).where(Operation.fingerprint == fingerprint,
                    Operation.created_at >= now - self.cfg.duplicate_window_seconds).limit(1)):
                blocked("DUPLICATE_REQUEST", 409)
            if db.scalar(select(Operation.id).where(Operation.status == "RUNNING").limit(1)):
                blocked("USAGE_BUSY")
            row = Operation(id=str(uuid4()), fingerprint=fingerprint, created_at=now, status="RUNNING")
            db.add(row); db.commit(); return row.id

    def finish_operation(self, operation_id, success):
        with self.lock, self.sessions() as db:
            row = db.get(Operation, operation_id)
            row.status = "SUCCESS" if success else "FAILED"
            db.commit()

    def estimate(self, path, body):
        if path == "/embeddings":
            texts = body.get("input")
            if not isinstance(texts, list) or not 1 <= len(texts) <= 10 or not all(isinstance(t, str) for t in texts):
                blocked("TOKEN_LIMIT", 422)
            units, outputs = sum(len(t.encode("utf-8")) for t in texts), 0
            rate = self.cfg.embedding_rate
        elif path == "/chat/completions":
            units = len(json.dumps(body["messages"], ensure_ascii=False).encode("utf-8")) + 256
            outputs, rate = self.cfg.max_output_tokens, self.cfg.qwen_input_rate
        else:
            blocked("USAGE_STOPPED", 503)
        if units > self.cfg.max_input_tokens: blocked("TOKEN_LIMIT", 422)
        cost = (Decimal(units) * rate + Decimal(outputs) * self.cfg.qwen_output_rate) / 1000000
        return units, outputs, cost

    def execute(self, path, body, send, error_code):
        if getattr(self.cfg, "rag_runtime_mode", None) != "real":
            raise AppError("MODEL_DISABLED", "Paid model execution is disabled", 403)
        units, outputs, cost = self.estimate(path, body)
        if not self.call_lock.acquire(blocking=False): blocked("USAGE_BUSY")
        call_id = None
        try:
            with self.lock, self.sessions() as db:
                state = self._state(db)
                if state.stopped: blocked("USAGE_STOPPED", 503)
                now = self._checked_time(db, state)
                window = usage_windows(now); day = window["day"]
                if db.scalar(select(ModelCall.id).where(ModelCall.status == "SENT_UNCERTAIN").limit(1)):
                    state.stopped, state.reason = True, "UNRESOLVED_PRIOR_REQUEST"
                    db.commit()
                    blocked("USAGE_STOPPED", 503)
                count = db.scalar(select(func.count()).select_from(ModelCall))
                if self.cfg.max_calls_total and count >= self.cfg.max_calls_total: blocked("USAGE_LIMIT")
                kind_limit = self.cfg.max_embedding_calls_total if not outputs else self.cfg.max_qwen_calls_total
                if kind_limit and db.scalar(select(func.count()).select_from(ModelCall).where(
                        ModelCall.kind == ("embedding" if not outputs else "qwen"))) >= kind_limit:
                    blocked("USAGE_LIMIT")
                daily_scope = (ModelCall.created_at >= window["day_start"], ModelCall.created_at < window["day_end"])
                month_scope = (ModelCall.created_at >= window["month_start"], ModelCall.created_at < window["month_end"])
                daily = db.scalar(select(func.count()).select_from(ModelCall).where(*daily_scope))
                charge = db.scalar(select(func.sum(ModelCall.charge_cny)).where(*daily_scope)) or Decimal(0)
                monthly = db.scalar(select(func.sum(ModelCall.charge_cny)).where(*month_scope)) or Decimal(0)
                if (daily >= self.cfg.max_calls_per_day or charge + cost > self.cfg.daily_budget_cny
                        or monthly + cost > self.cfg.monthly_budget_cny): blocked("USAGE_LIMIT")
                recent = db.scalar(select(func.count()).select_from(ModelCall).where(ModelCall.created_at > now - 60))
                if recent >= self.cfg.model_requests_per_minute: blocked("USAGE_RATE_LIMIT")
                call_id = str(uuid4())
                db.add(ModelCall(id=call_id, kind="embedding" if not outputs else "qwen", created_at=now,
                    day=day, status="SENT_UNCERTAIN", estimated_input=units, reserved_output=outputs, charge_cny=cost))
                db.commit()
            self._audit("MODEL_RESERVED", call_id=call_id, kind="embedding" if not outputs else "qwen", reserved_cny=str(cost))
            try:
                result = send(body)
                usage = result.get("usage", {})
                inputs = usage.get("prompt_tokens", usage.get("input_tokens", usage.get("total_tokens") if not outputs else None))
                actual_outputs = usage.get("completion_tokens") if outputs else 0
                if type(inputs) is not int or type(actual_outputs) is not int or inputs < 0 or actual_outputs < 0:
                    raise ValueError()
                rate = self.cfg.qwen_input_rate if outputs else self.cfg.embedding_rate
                actual_cost = (Decimal(inputs) * rate + Decimal(actual_outputs) * self.cfg.qwen_output_rate) / 1000000
                with self.sessions() as db:
                    row = db.get(ModelCall, call_id)
                    row.input_tokens, row.output_tokens = inputs, actual_outputs
                    row.charge_cny = max(cost, actual_cost)  # Keep conservative reservation, never refund unknown usage.
                    db.commit()
                if inputs > units or inputs > self.cfg.max_input_tokens or actual_outputs > outputs:
                    raise ValueError()
                if outputs:
                    choice = result["choices"][0]
                    if choice.get("finish_reason") != "stop" or choice["message"].get("reasoning_content"):
                        raise ValueError()
                with self.sessions() as db:
                    db.get(ModelCall, call_id).status = "VERIFIED"; db.commit()
                self._audit("MODEL_VERIFIED", call_id=call_id, input_tokens=inputs, output_tokens=actual_outputs, estimated_cny=str(actual_cost))
                return result
            except Exception:
                with self.sessions() as db:
                    db.get(ModelCall, call_id).status = "UNKNOWN"; db.commit()
                self.stop("MODEL_OR_USAGE_UNCERTAIN")
                raise AppError(error_code, "模型请求失败或用量未确认，已暂停后续调用，请勿重复提交。", 503) from None
        finally:
            self.call_lock.release()

    def summary(self):
        with self.sessions() as db:
            calls = db.scalars(select(ModelCall)).all(); state = db.get(GuardState, 1)
            floor = persisted_time_floor(db, state)
            if floor is None:
                blocked("USAGE_STOPPED", 503)
            sample = sample_clock(self.clock, self.monotonic)
            now = sample[0]
            if self.cfg.strict_clock_protection:
                now = floor
                if state.reason != "CLOCK_REVIEW_REQUIRED" and state.clock_epoch == self.clock_epoch and self._clock_consistent(sample):
                    now = max(floor, self._projected_bounds(sample)[0])
            if state.reason == "CLOCK_REVIEW_REQUIRED" or state.clock_epoch != self.clock_epoch:
                now = floor
            window = usage_windows(now)
            daily = [c for c in calls if window["day_start"] <= c.created_at < window["day_end"]]
            monthly = [c for c in calls if window["month_start"] <= c.created_at < window["month_end"]]
            return {"day_utc": window["day"], "month_utc": window["month"],
                "daily_attempts": len(daily), "daily_reserved_cny": str(sum((c.charge_cny for c in daily), Decimal(0))),
                "monthly_attempts": len(monthly), "monthly_reserved_cny": str(sum((c.charge_cny for c in monthly), Decimal(0))),
                "daily_budget_cny": str(self.cfg.daily_budget_cny), "monthly_budget_cny": str(self.cfg.monthly_budget_cny),
                "last_observed_at": state.last_observed_at, "clock_epoch": state.clock_epoch,
                "historical_baseline": state.historical_requests, "r1_reserved_attempts": len(calls),
                "r1_verified_requests": sum(c.status == "VERIFIED" for c in calls),
                "cumulative_attempt_upper_bound": state.historical_requests + len(calls),
                "estimated_reserved_cny": str(sum((c.charge_cny for c in calls), Decimal(0))),
                "input_tokens": sum(c.input_tokens for c in calls), "output_tokens": sum(c.output_tokens for c in calls),
                "stopped": state.stopped, "reason": state.reason}