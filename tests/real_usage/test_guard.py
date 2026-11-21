from decimal import Decimal
from types import SimpleNamespace
import httpx
import pytest
from pydantic import SecretStr, ValidationError
from app.core.errors import AppError
from app.real_usage.config import RealUsageSettings
from app.real_usage.guard import UsageGuard
from app.real_usage.models import GuardedModels


def test_real_settings_are_strict_and_credential_free_by_default(settings):
    public = settings.model_dump()
    public.update(audit_dir="/audit")
    for changes in [
        {"dashscope_api_key": SecretStr("")}, {"embedding_dimension": 768},
        {"qwen_base_url": "http://invalid.example"}, {"qwen_model": "different"},
        {"database_url": SecretStr("sqlite:///other.db")}, {"vector_uri": "/demo/milvus.db"},
        {"max_calls_total": -1}, {"historical_model_requests": 0},
    ]:
        with pytest.raises(ValidationError):
            RealUsageSettings(_env_file=None, **{**public, **changes})


def result(tokens=8):
    return {"usage": {"prompt_tokens": tokens}, "data": []}


def test_request_limit_is_persisted_and_cannot_reset_on_restart(guard):
    g, clock, engine, sessions = guard
    for _ in range(3): g.execute("/embeddings", {"input": ["synthetic"]}, lambda _: result(), "EMBEDDING_ERROR")
    again = UsageGuard(engine, sessions, g.cfg, clock=lambda: clock[0])
    sent = []
    with pytest.raises(AppError) as exc:
        again.execute("/embeddings", {"input": ["synthetic"]}, lambda b: sent.append(b), "EMBEDDING_ERROR")
    assert exc.value.code == "USAGE_LIMIT" and not sent
    assert again.summary()["historical_baseline"] == 6
    assert again.summary()["cumulative_attempt_upper_bound"] == 9


def test_rate_and_daily_reservation_block_before_transport(guard):
    g, clock, _, _ = guard
    g.cfg = g.cfg.model_copy(update={"model_requests_per_minute": 1, "max_calls_total": 0})
    g.execute("/embeddings", {"input": ["synthetic"]}, lambda _: result(), "EMBEDDING_ERROR")
    with pytest.raises(AppError) as exc:
        g.execute("/embeddings", {"input": ["synthetic"]}, lambda _: pytest.fail("Unexpected transport"), "EMBEDDING_ERROR")
    assert exc.value.code == "USAGE_RATE_LIMIT"
    clock[0] += 61
    g.cfg = g.cfg.model_copy(update={"daily_budget_cny": Decimal("0.000001")})
    with pytest.raises(AppError) as exc:
        g.execute("/embeddings", {"input": ["synthetic"]}, lambda _: pytest.fail("Unexpected transport"), "EMBEDDING_ERROR")
    assert exc.value.code == "USAGE_LIMIT" and g.summary()["r1_reserved_attempts"] == 1


def test_timeout_is_counted_once_stops_future_calls_and_survives_restart(guard):
    g, clock, engine, sessions = guard
    def timeout(_): raise httpx.ReadTimeout("fictional upstream failure")
    with pytest.raises(AppError):
        g.execute("/embeddings", {"input": ["synthetic"]}, timeout, "EMBEDDING_ERROR")
    assert g.summary()["r1_reserved_attempts"] == 1 and g.summary()["stopped"]
    again = UsageGuard(engine, sessions, g.cfg, clock=lambda: clock[0])
    with pytest.raises(AppError) as exc:
        again.execute("/embeddings", {"input": ["synthetic"]}, lambda _: pytest.fail("Automatic retry"), "EMBEDDING_ERROR")
    assert exc.value.code == "USAGE_STOPPED"
    reserved = again.summary()["estimated_reserved_cny"]
    again.acknowledge_stop()
    assert again.summary()["r1_reserved_attempts"] == 1
    assert again.summary()["estimated_reserved_cny"] == reserved


def test_missing_or_overlimit_usage_is_not_refunded(guard):
    g, _, _, _ = guard
    with pytest.raises(AppError):
        g.execute("/embeddings", {"input": ["synthetic"]}, lambda _: {}, "EMBEDDING_ERROR")
    assert Decimal(g.summary()["estimated_reserved_cny"]) > 0
    assert g.summary()["stopped"]


def test_operation_duplicate_and_busy_state_are_persistent(guard):
    g, clock, engine, sessions = guard
    first = g.begin_operation("fictional-owner", "fictional-kb", "upload", "a" * 64)
    for digest, expected in [("a" * 64, "DUPLICATE_REQUEST"), ("b" * 64, "USAGE_BUSY")]:
        with pytest.raises(AppError) as exc:
            g.begin_operation("fictional-owner", "fictional-kb", "upload", digest)
        assert exc.value.code == expected
    g.finish_operation(first, True)
    again = UsageGuard(engine, sessions, g.cfg, clock=lambda: clock[0])
    with pytest.raises(AppError) as exc:
        again.begin_operation("fictional-owner", "fictional-kb", "upload", "a" * 64)
    assert exc.value.code == "DUPLICATE_REQUEST"
    clock[0] += 301
    op = again.begin_operation("fictional-owner", "fictional-kb", "upload", "a" * 64)
    again.finish_operation(op, True)


def test_interrupted_operation_blocks_startup_until_acknowledged(guard):
    g, clock, engine, sessions = guard
    g.begin_operation("fictional-owner", "fictional-kb", "message", "a" * 64)
    again = UsageGuard(engine, sessions, g.cfg, clock=lambda: clock[0])
    assert again.summary()["stopped"] and again.summary()["reason"] == "PROCESS_INTERRUPTED"


def test_upstream_concurrency_is_nonblocking(guard):
    g, _, _, _ = guard
    def outer(_):
        with pytest.raises(AppError) as exc:
            g.execute("/embeddings", {"input": ["synthetic"]}, lambda _: pytest.fail("Parallel transport"), "EMBEDDING_ERROR")
        assert exc.value.code == "USAGE_BUSY"
        return result()
    g.execute("/embeddings", {"input": ["synthetic"]}, outer, "EMBEDDING_ERROR")
    assert g.summary()["r1_reserved_attempts"] == 1


def test_token_gate_blocks_all_oversized_chunks_before_first_request(guard):
    g, _, _, _ = guard
    models = GuardedModels(g.cfg, g, client_factory=lambda **_: pytest.fail("Unexpected HTTP"))
    with pytest.raises(AppError) as exc:
        models.embed(["small", "a" * (g.cfg.max_input_tokens + 1)])
    assert exc.value.code == "TOKEN_LIMIT" and g.summary()["r1_reserved_attempts"] == 0


def test_output_limit_non_thinking_and_no_retry_transport(guard):
    import json
    g, _, _, _ = guard
    seen = []
    def wire(request):
        payload = json.loads(request.content)
        seen.append(payload)
        assert payload["max_tokens"] == 256 and payload["enable_thinking"] is False and payload["stream"] is False
        assert "authorization" in request.headers
        return httpx.Response(200, json={"usage": {"prompt_tokens": 20, "completion_tokens": 12},
            "choices": [{"finish_reason": "stop", "message": {"content": '{"answer":"17 days [1]","source_ids":[1]}'}}]})
    def client(**kwargs):
        kwargs.pop("transport").close()
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        return httpx.Client(transport=httpx.MockTransport(wire), **kwargs)
    answer, ids = GuardedModels(g.cfg, g, client).answer("synthetic policy", [{"text": "17 days"}], [])
    assert ids == [1] and "17" in answer and len(seen) == 1
    log = (g.cfg.audit_dir / "usage.jsonl").read_text(encoding="utf-8")
    assert "synthetic policy" not in log and "authorization" not in log.lower()
def test_unresolved_request_cannot_be_bypassed_after_storage_recovery(guard):
    from app.real_usage.guard import ModelCall
    g,clock,engine,sessions=guard
    with sessions() as db:
        db.add(ModelCall(id="fictional-pending",kind="embedding",created_at=clock[0],day="2027-01-15",
            status="SENT_UNCERTAIN",estimated_input=10,reserved_output=0,charge_cny=Decimal("0.000005")))
        db.commit()
    with pytest.raises(AppError) as exc:
        g.execute("/embeddings",{"input":["synthetic"]},lambda _:pytest.fail("Unresolved previous call"),"EMBEDDING_ERROR")
    assert exc.value.code=="USAGE_STOPPED" and g.summary()["r1_reserved_attempts"]==1
    again=UsageGuard(engine,sessions,g.cfg,clock=lambda:clock[0])
    again.acknowledge_stop()
    assert again.summary()["r1_reserved_attempts"]==1 and not again.summary()["stopped"]