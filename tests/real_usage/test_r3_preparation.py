import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock
import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
import yaml
from app.core.errors import AppError
from app.real_usage.config import RealUsageSettings
from app.real_usage.guard import UsageGuard, ModelCall
from app.real_usage.models import GuardedModels
import real_usage_runtime as runtime

ROOT = Path(__file__).resolve().parents[2]


def configure(guard):
    usage, clock, engine, sessions = guard
    usage.cfg = usage.cfg.model_copy(update={
        "max_calls_total": 10, "max_embedding_calls_total": 2, "max_qwen_calls_total": 1})
    return usage, clock, engine, sessions


def invoke(usage, kind, send=None):
    if kind == "embedding":
        return usage.execute("/embeddings", {"input": ["synthetic"]},
            send or (lambda _: {"usage": {"prompt_tokens": 1}}), "EMBEDDING_ERROR")
    return usage.execute("/chat/completions", {"messages": [{"role": "user", "content": "synthetic"}]},
        send or (lambda _: {"usage": {"prompt_tokens": 1, "completion_tokens": 1},
            "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]}), "MODEL_UNAVAILABLE")


@pytest.mark.parametrize("kind,limit", [("embedding", 2), ("qwen", 1)])
def test_each_kind_has_its_own_persistent_cap(guard, kind, limit):
    usage, clock, engine, sessions = configure(guard)
    for _ in range(limit):
        invoke(usage, kind)
    send = Mock()
    with pytest.raises(AppError) as error:
        invoke(usage, kind, send)
    assert error.value.code == "USAGE_LIMIT"
    send.assert_not_called()
    restarted = UsageGuard(engine, sessions, usage.cfg, clock=lambda: clock[0])
    with pytest.raises(AppError) as error:
        invoke(restarted, kind, send)
    assert error.value.code == "USAGE_LIMIT"
    assert restarted.summary()["r1_reserved_attempts"] == limit
    assert restarted.summary()["historical_baseline"] == 6


def test_reaching_embedding_cap_does_not_consume_qwen_slot(guard):
    usage, _, _, sessions = configure(guard)
    invoke(usage, "embedding"); invoke(usage, "embedding")
    invoke(usage, "qwen")
    with sessions() as db:
        counts = dict(db.execute(select(ModelCall.kind, func.count()).group_by(ModelCall.kind)).all())
    assert counts == {"embedding": 2, "qwen": 1}
    for kind in counts:
        with pytest.raises(AppError) as error:
            invoke(usage, kind, Mock())
        assert error.value.code == "USAGE_LIMIT"


def test_unknown_prior_reservation_counts_toward_kind_limit(guard):
    usage, clock, _, sessions = configure(guard)
    usage.cfg = usage.cfg.model_copy(update={"max_embedding_calls_total": 1})
    with sessions() as db:
        db.add(ModelCall(id="fictional-unknown", kind="embedding", created_at=clock[0],
            day="2027-01-15", status="UNKNOWN", estimated_input=9, reserved_output=0,
            input_tokens=0, output_tokens=0, charge_cny=Decimal("0.000005")))
        db.commit()
    send = Mock()
    with pytest.raises(AppError) as error:
        invoke(usage, "embedding", send)
    assert error.value.code == "USAGE_LIMIT"
    send.assert_not_called()
    assert usage.summary()["r1_reserved_attempts"] == 1


def test_timeout_is_one_attempt_and_no_further_kind_can_send(guard):
    usage, clock, engine, sessions = configure(guard)
    send = Mock(side_effect=httpx.ReadTimeout("fictional timeout"))
    with pytest.raises(AppError):
        invoke(usage, "embedding", send)
    send.assert_called_once()
    restarted = UsageGuard(engine, sessions, usage.cfg, clock=lambda: clock[0])
    next_send = Mock()
    for kind in ["embedding", "qwen"]:
        with pytest.raises(AppError) as error:
            invoke(restarted, kind, next_send)
        assert error.value.code == "USAGE_STOPPED"
    next_send.assert_not_called()
    assert restarted.summary()["r1_reserved_attempts"] == 1
    with sessions() as db:
        row = db.scalar(select(ModelCall))
        assert row.kind == "embedding" and row.status == "UNKNOWN"


def test_zero_kind_caps_preserve_legacy_total_cap(guard):
    usage, _, _, _ = guard
    assert usage.cfg.max_embedding_calls_total == usage.cfg.max_qwen_calls_total == 0
    for _ in range(3):
        invoke(usage, "embedding")
    send = Mock()
    with pytest.raises(AppError) as error:
        invoke(usage, "embedding", send)
    assert error.value.code == "USAGE_LIMIT"
    send.assert_not_called()


@pytest.mark.parametrize("changes", [
    {"max_embedding_calls_total": -1}, {"max_qwen_calls_total": -1},
    {"max_embedding_calls_total": 1000001}, {"max_qwen_calls_total": 1000001}])
def test_kind_cap_values_are_validated(settings, changes):
    values = settings.model_dump()
    values["audit_dir"] = "/audit"
    with pytest.raises(ValidationError):
        RealUsageSettings(_env_file=None, **{**values, **changes})


def test_reviewed_limits_cannot_disable_or_raise_kind_caps(settings):
    cfg = settings.model_copy(update={"max_embedding_calls_total": 2, "max_qwen_calls_total": 1})
    plan = {"limits": {"max_calls_total": 3, "max_embedding_calls_total": 2,
        "max_qwen_calls_total": 1, "daily_budget_cny": "0.01"}}
    runtime.validate_limits(cfg, plan)
    for changes in [{"max_embedding_calls_total": 0}, {"max_embedding_calls_total": 3},
                    {"max_qwen_calls_total": 0}, {"max_qwen_calls_total": 2}]:
        with pytest.raises(runtime.Stop, match="R1_APPROVED_LIMITS_MISMATCH"):
            runtime.validate_limits(cfg.model_copy(update=changes), plan)


def test_guarded_adapter_uses_exactly_two_embedding_one_qwen_without_retries(guard):
    usage, _, _, _ = configure(guard)
    usage.cfg = usage.cfg.model_copy(update={"max_calls_total": 3})
    sent, clients = [], []
    def wire(request):
        body = json.loads(request.content)
        sent.append(request.url.path)
        if request.url.path.endswith("/embeddings"):
            assert body["dimensions"] == 1024
            return httpx.Response(200, json={"usage": {"prompt_tokens": 1},
                "data": [{"index": 0, "embedding": [1.0] + [0.0] * 1023}]})
        assert body["max_tokens"] == 256 and body["enable_thinking"] is False and body["stream"] is False
        return httpx.Response(200, json={"usage": {"prompt_tokens": 2, "completion_tokens": 4},
            "choices": [{"finish_reason": "stop", "message": {"content": '{"answer":"17 days [1]","source_ids":[1]}'}}]})
    def factory(**kwargs):
        transport = kwargs.pop("transport")
        assert transport._pool._retries == 0
        transport.close()
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False and kwargs["timeout"] == 30
        clients.append(True)
        return httpx.Client(transport=httpx.MockTransport(wire), **kwargs)
    models = GuardedModels(usage.cfg, usage, factory)
    assert len(models.embed(["document"])[0]) == 1024
    models.embed(["question"])
    answer, ids = models.answer("synthetic question", [{"text": "17 days"}], [])
    assert ids == [1] and "17" in answer
    with pytest.raises(AppError):
        models.embed(["extra question"])
    assert len(clients) == 3 and sent == ["/compatible-mode/v1/embeddings", "/compatible-mode/v1/embeddings", "/compatible-mode/v1/chat/completions"]
    assert usage.summary()["r1_reserved_attempts"] == 3


def test_r3_compose_changes_only_backend_and_reuses_all_persistence():
    infra = yaml.safe_load((ROOT / "deploy/real-usage/compose.infrastructure.yml").read_text())
    real = yaml.safe_load((ROOT / "deploy/real-usage/compose.r3-real.yml").read_text())
    for section in ["name", "volumes", "secrets", "networks"]:
        assert real[section] == infra[section]
    for service in ["real-frontend", "real-postgres"]:
        assert real["services"][service] == infra["services"][service]
    before, after = infra["services"]["real-backend"], real["services"]["real-backend"]
    assert before["image"] == "rag-knowledge-real-backend:r2-infrastructure"
    assert after["image"] == "rag-knowledge-real-backend:r3-real-candidate"
    assert after["restart"] == "no"
    assert after["command"][-2:] == ["--approval-file", "/opt/rag/deploy/real-usage/approval.r3-real.json"]
    env = after["environment"]
    assert (env["RAG_RUNTIME_MODE"], env["MODEL_BACKEND"], env["ALLOW_PAID_MODELS"]) == ("real", "qwen", "true")
    assert env["MAX_EMBEDDING_CALLS_TOTAL"] == "2" and env["MAX_QWEN_CALLS_TOTAL"] == "1"
    assert env["EMBEDDING_DIMENSION"] == "1024" and env["EMBEDDING_MODEL"] == "text-embedding-v4"
    assert env["QWEN_MODEL"] == "qwen-plus" and env["QWEN_BASE_URL"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert "DASHSCOPE_API_KEY" not in env and "env_file" not in after
    assert after["volumes"][:-1] == before["volumes"]
    key_mount = after["volumes"][-1]
    assert key_mount["source"] == "../../backend/.env" and key_mount["read_only"] is True
    assert key_mount["target"] == "/run/secrets/model.env" and not key_mount["bind"]["create_host_path"]
    assert after["secrets"] == before["secrets"] and after["networks"] == before["networks"]
