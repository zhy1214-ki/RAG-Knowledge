"""R4 offline-only quota tests. Temporary SQLite and Mock transports, no live data."""
import importlib.util
import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from unittest.mock import Mock
import httpx
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError
from app.core.db import make_database
from app.core.errors import AppError
from app.real_usage.guard import UsageGuard, GuardState, ModelCall, usage_windows
import real_usage_runtime as runtime
ROOT=Path(__file__).resolve().parents[2]

class Clock:
    def __init__(self, value="2027-01-15T12:00:00+00:00"):
        self.wall=datetime.fromisoformat(value).timestamp(); self.tick=1000.0
    def advance(self, seconds): self.wall+=seconds; self.tick+=seconds

@pytest.fixture
def daily(settings, tmp_path):
    cfg=settings.model_copy(update={"strict_clock_protection":True,"max_calls_total":1000,
        "max_embedding_calls_total":1000,"max_qwen_calls_total":1000,
        "daily_budget_cny":Decimal("0.10"),"monthly_budget_cny":Decimal("3")})
    engine,sessions=make_database("sqlite:///"+(tmp_path/"r4.db").as_posix())
    clock=Clock()
    guard=UsageGuard(engine,sessions,cfg,clock=lambda:clock.wall,monotonic=lambda:clock.tick)
    yield guard,clock,engine,sessions
    engine.dispose()

def restart(data):
    guard,clock,engine,sessions=data
    return UsageGuard(engine,sessions,guard.cfg,clock=lambda:clock.wall,monotonic=lambda:clock.tick)

def embed(guard, send=None):
    return guard.execute("/embeddings",{"input":["abcdefgh"]},send or (lambda _: {"usage":{"prompt_tokens":1}}),"EMBEDDING_ERROR")

def denied(guard, code="USAGE_LIMIT"):
    send=Mock()
    with pytest.raises(AppError) as error: embed(guard,send)
    assert error.value.code==code
    send.assert_not_called()


def test_daily_reservation_exact_boundary_and_rejection(daily):
    g,_,_,_=daily; g.cfg=g.cfg.model_copy(update={"daily_budget_cny":Decimal("0.000008")})
    embed(g); embed(g); denied(g)
    assert g.summary()["daily_reserved_cny"]=="0.00000800"
    assert g.summary()["r1_reserved_attempts"]==2


def test_monthly_limit_aggregates_prior_days(daily):
    g,clock,_,_=daily;g.cfg=g.cfg.model_copy(update={"monthly_budget_cny":Decimal("0.000008")})
    embed(g);clock.advance(86400);embed(g);clock.advance(86400);denied(g)
    assert g.summary()["daily_attempts"]==0
    assert Decimal(g.summary()["monthly_reserved_cny"])==Decimal("0.000008")


def test_continuous_utc_day_rollover_preserves_lifetime_and_month(daily):
    g,clock,_,_=daily;g.cfg=g.cfg.model_copy(update={"max_calls_per_day":1})
    embed(g);denied(g);clock.advance(86400);embed(g)
    status=g.summary();assert status["daily_attempts"]==1 and status["monthly_attempts"]==2
    assert status["r1_reserved_attempts"]==2 and status["historical_baseline"]==6


def test_continuous_month_rollover_and_previous_month_kept(daily):
    g,clock,_,_=daily
    clock.advance(datetime(2027,2,1,tzinfo=timezone.utc).timestamp()-clock.wall-1)
    g.cfg=g.cfg.model_copy(update={"monthly_budget_cny":Decimal("0.000004")})
    embed(g);denied(g);clock.advance(1);embed(g)
    assert g.summary()["month_utc"]=="2027-02" and g.summary()["monthly_attempts"]==1
    assert g.summary()["r1_reserved_attempts"]==2


def test_month_windows_are_utc_and_handle_leap_year():
    stamp=datetime.fromisoformat("2028-02-29T23:59:59+00:00").timestamp()
    window=usage_windows(stamp)
    assert window["day"]=="2028-02-29" and window["month"]=="2028-02"
    assert window["month_end"]==datetime(2028,3,1,tzinfo=timezone.utc).timestamp()
    assert usage_windows(datetime(2027,12,31,tzinfo=timezone.utc).timestamp())["month_end"]==datetime(2028,1,1,tzinfo=timezone.utc).timestamp()


def test_editing_display_day_cannot_bypass_created_at_budget(daily):
    g,_,_,sessions=daily;g.cfg=g.cfg.model_copy(update={"max_calls_per_day":1})
    embed(g)
    with sessions() as db:
        db.scalar(sa.select(ModelCall)).day="2099-12-31";db.commit()
    denied(g);assert g.summary()["daily_attempts"]==1


def test_total_cap_survives_calendar_rollover_and_restart(daily):
    g,clock,_,_=daily;g.cfg=g.cfg.model_copy(update={"max_calls_total":1})
    embed(g);again=restart(daily);denied(again)
    clock.advance(86400);denied(g)
    assert again.summary()["r1_reserved_attempts"]==1


def test_daily_budget_survives_same_day_restart(daily):
    g,_,_,_=daily;g.cfg=g.cfg.model_copy(update={"daily_budget_cny":Decimal("0.000004")})
    embed(g);again=restart(daily);denied(again)
    assert Decimal(again.summary()["daily_reserved_cny"])==Decimal("0.000004")


def test_unknown_keeps_monthly_reservation_after_ack_and_restart(daily):
    g,clock,_,sessions=daily;g.cfg=g.cfg.model_copy(update={"monthly_budget_cny":Decimal("0.000004")})
    send=Mock(side_effect=httpx.ReadTimeout("fictional timeout"))
    with pytest.raises(AppError):embed(g,send)
    send.assert_called_once();again=restart(daily);denied(again,"USAGE_STOPPED")
    again.acknowledge_stop();denied(again)
    with sessions() as db:assert db.scalar(sa.select(ModelCall)).status=="UNKNOWN"
    assert Decimal(again.summary()["monthly_reserved_cny"])==Decimal("0.000004")


def test_restart_across_day_requires_clock_ack_without_refunding(daily):
    g,clock,_,_=daily;embed(g);old=g.summary()["estimated_reserved_cny"]
    clock.advance(86400);again=restart(daily)
    denied(again,"USAGE_STOPPED")
    assert again.summary()["reason"]=="CLOCK_REVIEW_REQUIRED"
    assert again.summary()["day_utc"]=="2027-01-15"
    with pytest.raises(AppError):again.acknowledge_stop()
    again.acknowledge_stop(acknowledge_clock=True)
    assert again.summary()["estimated_reserved_cny"]==old
    embed(again);assert again.summary()["r1_reserved_attempts"]==2


@pytest.mark.parametrize("jump",[-1,3600,86400*40])
def test_wall_clock_changes_stop_before_reservation(daily,jump):
    g,clock,_,_=daily;embed(g);clock.wall+=jump
    denied(g,"USAGE_STOPPED")
    assert g.summary()["r1_reserved_attempts"]==1 and g.summary()["reason"]=="CLOCK_REVIEW_REQUIRED"
    assert g.summary()["monthly_attempts"]==1


def test_clock_ack_cannot_confirm_time_before_persisted_request(daily):
    g,clock,_,_=daily;embed(g);clock.wall-=10
    denied(g,"USAGE_STOPPED")
    with pytest.raises(AppError):g.acknowledge_stop(acknowledge_clock=True)
    assert g.summary()["stopped"] and g.summary()["clock_epoch"]==0


def test_clock_epoch_reanchors_an_existing_guard_without_reset(daily):
    g,clock,_,_=daily;other=restart(daily);embed(g)
    clock.wall+=3600;denied(g,"USAGE_STOPPED")
    clock.wall-=3600;g.acknowledge_stop(acknowledge_clock=True)
    embed(other)
    assert other.summary()["clock_epoch"]==1 and other.summary()["r1_reserved_attempts"]==2


def test_duplicate_submit_remains_blocked_after_restart(daily):
    g,_,_,_=daily;operation=g.begin_operation("synthetic","kb","message","same")
    g.finish_operation(operation,True);again=restart(daily)
    with pytest.raises(AppError) as error:again.begin_operation("synthetic","kb","message","same")
    assert error.value.code=="DUPLICATE_REQUEST"
    assert again.summary()["r1_reserved_attempts"]==0


def test_independent_guards_serialize_sqlite_reservations(daily):
    g,_,engine,sessions=daily;other=restart(daily)
    g.cfg=other.cfg=g.cfg.model_copy(update={"max_calls_total":1,"monthly_budget_cny":Decimal("0.000004")})
    barrier=Barrier(2);sends=[];statements=[]
    def trace(conn,cursor,statement,parameters,context,executemany):statements.append(statement)
    sa.event.listen(engine,"before_cursor_execute",trace)
    def worker(guard):
        barrier.wait(timeout=5)
        try:
            embed(guard,lambda _:sends.append(1) or {"usage":{"prompt_tokens":1}})
            return "OK"
        except AppError as error:return error.code
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(worker,[g,other]))
    finally:sa.event.remove(engine,"before_cursor_execute",trace)
    assert results.count("OK")==1 and len(sends)==1
    assert all(x in {"OK","USAGE_LIMIT","USAGE_STOPPED"} for x in results)
    assert any(x=="BEGIN IMMEDIATE" for x in statements)
    with sessions() as db:assert db.scalar(sa.select(sa.func.count()).select_from(ModelCall))==1


def test_postgres_state_lock_compiles_without_connecting():
    from sqlalchemy.dialects import postgresql
    statement=sa.select(GuardState).where(GuardState.id==1).with_for_update()
    assert "FOR UPDATE" in str(statement.compile(dialect=postgresql.dialect()))


@pytest.mark.parametrize("value",["0","-1","NaN","Infinity"])
def test_monthly_budget_rejects_invalid_values(settings,value):
    values=settings.model_dump();values["audit_dir"]="/audit";values["monthly_budget_cny"]=value
    with pytest.raises(ValidationError):type(settings)(_env_file=None,**values)


def test_monthly_and_clock_policy_bound_by_approval(daily):
    g,_,_,_=daily
    approved={"limits":{"monthly_budget_cny":"3","daily_budget_cny":"0.10","strict_clock_protection":True,"max_calls_total":1000}}
    runtime.validate_limits(g.cfg,approved)
    for changes in [{"monthly_budget_cny":Decimal("3.01")},{"daily_budget_cny":Decimal("0.11")},{"strict_clock_protection":False},{"max_calls_total":1001}]:
        with pytest.raises(runtime.Stop):runtime.validate_limits(g.cfg.model_copy(update=changes),approved)


def load_migration(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/("backend/real_usage_migrations/versions/"+name+".py"))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def test_additive_migration_preserves_three_prior_requests_and_six_baseline(tmp_path):
    engine,_=make_database("sqlite:///"+(tmp_path/"migration.db").as_posix())
    base=load_migration("r1_001_guard");new=load_migration("r4_002_clock")
    with engine.begin() as connection:
        ops=Operations(MigrationContext.configure(connection));base.op=ops;base.upgrade()
        connection.execute(sa.text("INSERT INTO real_usage_guard(id,stopped,reason,historical_requests) VALUES(1,false,'',6)"))
        for i in range(3):
            connection.execute(sa.text("INSERT INTO real_usage_calls VALUES(:id,:kind,:created,'2026-11-19','VERIFIED',10,0,1,0,0.00001)"),{"id":"fictional-"+str(i),"kind":"qwen" if i==2 else "embedding","created":1795087588+i})
        before=list(connection.execute(sa.text("SELECT * FROM real_usage_calls ORDER BY id")))
        new.op=ops;new.upgrade()
        assert list(connection.execute(sa.text("SELECT * FROM real_usage_calls ORDER BY id")))==before
        assert tuple(connection.execute(sa.text("SELECT historical_requests,last_observed_at,clock_epoch FROM real_usage_guard")).one())==(6,0,0)
    engine.dispose()
    buffer=io.StringIO();new.op=Operations(MigrationContext.configure(dialect_name="postgresql",opts={"as_sql":True,"output_buffer":buffer}));new.upgrade()
    ddl=buffer.getvalue();assert "ADD COLUMN last_observed_at" in ddl and "ADD COLUMN clock_epoch" in ddl
    assert "DELETE" not in ddl and "TRUNCATE" not in ddl and "UPDATE" not in ddl


def test_operator_status_and_explicit_clock_ack_use_only_offline_database(daily,monkeypatch,capsys):
    g,clock,engine,sessions=daily;embed(g);clock.advance(86400);again=restart(daily)
    original=Path;target=g.cfg.audit_dir/"operator.jsonl"
    monkeypatch.setattr(runtime,"database_url",lambda:"offline-test-database")
    monkeypatch.setattr("app.core.db.make_database",lambda _: (engine,sessions))
    monkeypatch.setattr(runtime,"Path",lambda p: target if p=="/audit/usage.jsonl" else original(p))
    monkeypatch.setattr("time.time",lambda:clock.wall)
    runtime.admin(False)
    status=json.loads(capsys.readouterr().out);assert status["day_utc"]=="2027-01-15" and status["r1_reserved_attempts"]==1
    with pytest.raises(runtime.Stop,match="R4_EXPLICIT_CLOCK_ACK_REQUIRED"):runtime.admin(True)
    runtime.admin(True,True)
    status=json.loads(capsys.readouterr().out)
    assert status["historical_baseline"]==6 and status["r1_reserved_attempts"]==1 and status["clock_epoch"]==1 and not status["stopped"]
    assert "OPERATOR_ACKNOWLEDGED_NO_REFUND" in target.read_text(encoding="utf-8")


def test_budget_rejection_and_audit_are_safe_and_do_not_log_payloads(daily):
    g,_,_,_=daily;embed(g);g.cfg=g.cfg.model_copy(update={"monthly_budget_cny":Decimal("0.000004")})
    denied(g)
    log=(g.cfg.audit_dir/"usage.jsonl").read_text(encoding="utf-8")
    assert "abcdefgh" not in log and "Authorization" not in log and "password" not in log and "DASHSCOPE" not in log


def test_pending_daily_profile_changes_only_backend_and_cannot_reuse_old_approval():
    import yaml
    before=yaml.safe_load((ROOT/"deploy/real-usage/compose.r3-real.yml").read_text(encoding="utf-8"))
    after=yaml.safe_load((ROOT/"deploy/real-usage/compose.r4-daily.yml").read_text(encoding="utf-8"))
    for name in ["name","volumes","secrets","networks"]:assert before[name]==after[name]
    for name in ["real-frontend","real-postgres"]:assert before["services"][name]==after["services"][name]
    service=after["services"]["real-backend"];env=service["environment"]
    assert service["image"]=="rag-knowledge-real-backend:r4-daily-candidate"
    assert service["command"][-1].endswith("approval.r4-daily.json")
    assert env["DAILY_BUDGET_CNY"]=="${R4_DAILY_BUDGET_CNY:-0.10}" and env["MONTHLY_BUDGET_CNY"]=="${R4_MONTHLY_BUDGET_CNY:-3}"
    assert env["STRICT_CLOCK_PROTECTION"]=="true" and env["MAX_CALLS_TOTAL"]=="${R4_MAX_CALLS_TOTAL:-1000}"
    assert "DASHSCOPE_API_KEY" not in env and "env_file" not in service
    assert service["volumes"]==before["services"]["real-backend"]["volumes"]
    example=(ROOT/"deploy/real-usage/r4-daily.env.example").read_text(encoding="utf-8")
    assert "APPROVAL_ID=" not in example and "API_KEY=" not in example


@pytest.mark.parametrize("shift",[-86400,86400])
def test_migrated_high_water_includes_operations_without_model_calls(daily,shift):
    from app.real_usage.guard import Operation
    g,clock,_,sessions=daily
    with sessions() as db:
        db.get(GuardState,1).last_observed_at=0  # Newly added migration column.
        db.add(Operation(id="fictional-quota-denied",fingerprint="offline-only",created_at=clock.wall,status="FAILED"))
        db.commit()
    clock.advance(shift)
    again=restart(daily)
    denied(again,"USAGE_STOPPED")
    assert again.summary()["reason"]=="CLOCK_REVIEW_REQUIRED"
    assert again.summary()["r1_reserved_attempts"]==0


@pytest.mark.parametrize("period",["day","month"])
def test_small_wall_correction_does_not_advance_billing_window(daily,period):
    g,clock,_,_=daily
    target="2027-01-15T23:59:45+00:00" if period=="day" else "2027-01-31T23:59:45+00:00"
    clock.advance(datetime.fromisoformat(target).timestamp()-clock.wall)
    field="daily_budget_cny" if period=="day" else "monthly_budget_cny"
    g.cfg=g.cfg.model_copy(update={field:Decimal("0.000004")})
    embed(g);clock.wall+=30  # Within tolerance, but not actual elapsed time.
    denied(g)
    assert g.summary()["r1_reserved_attempts"]==1
    assert g.summary()["day_utc"]==target[:10]
    assert g.summary()["month_utc"]==target[:7]


def test_pending_rate_covers_maximal_upload_and_one_question():
    import yaml
    profile=yaml.safe_load((ROOT/"deploy/real-usage/compose.r4-daily.yml").read_text(encoding="utf-8"))
    env=profile["services"]["real-backend"]["environment"]
    assert env["MODEL_REQUESTS_PER_MINUTE"]=="${R4_MODEL_REQUESTS_PER_MINUTE:-60}"
    # At most 32 one-chunk batches plus query Embedding and Qwen, without retries.
    assert 60>=int(env["MAX_DOCUMENT_CHUNKS"])+2
    assert env["MAX_CALLS_PER_DAY"]=="${R4_MAX_CALLS_PER_DAY:-60}"
