import ast
import hashlib
import json
from pathlib import Path
from threading import RLock
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock
import httpx
import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy.engine import make_url
from app.core.errors import AppError
from app.real_usage.config import RealUsageSettings
from app.real_usage.guard import UsageGuard
from app.real_usage.models import GuardedModels
from app.rag.providers import DisabledModels, QwenModels, get_models, make_models
import app.real_usage.application as application
import real_usage_runtime as runtime
import prepare_real_usage as preparation
import yaml

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def no_database_or_model_client(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail("R2_OFFLINE_EXTERNAL_OPERATION_FORBIDDEN")
    monkeypatch.setattr(httpx, "Client", denied)
    monkeypatch.setattr("app.core.db.make_database", denied)
    monkeypatch.setattr("app.factory.make_database", denied)
    monkeypatch.setattr("sqlalchemy.create_engine", denied)


def configuration(mode="infrastructure", **changes):
    values = dict(rag_runtime_mode=mode,
        database_url=SecretStr("postgresql+psycopg://rag_real:fictional@real-postgres/rag_personal_real"),
        jwt_secret=SecretStr("offline-r2-signing-material-" * 2),
        model_backend="mock" if mode == "infrastructure" else "qwen",
        allow_paid_models=mode == "real",
        dashscope_api_key=SecretStr("" if mode == "infrastructure" else "fictional-r2-key"))
    values.update(changes)
    return RealUsageSettings(_env_file=None, **values)


def test_key_free_settings_have_isolated_postgres_milvus_and_backup_scope():
    cfg = configuration()
    url = make_url(cfg.database_url.get_secret_value())
    assert (url.drivername, url.host, url.username, url.database) == (
        "postgresql+psycopg", "real-postgres", "rag_real", "rag_personal_real")
    assert cfg.vector_uri == "/data/milvus.db" and cfg.embedding_dimension == 1024
    assert cfg.storage_dir.as_posix() == "/data/uploads" and cfg.audit_dir.as_posix() == "/audit"
    assert not cfg.allow_paid_models and not cfg.dashscope_api_key.get_secret_value()
    import real_usage_backup as backup
    assert backup.ROOT == ROOT and (backup.ROOT / "data/real-usage-backups").is_relative_to(ROOT)


@pytest.mark.parametrize("changes", [
    {"rag_runtime_mode": ""}, {"rag_runtime_mode": "automatic"},
    {"model_backend": "qwen"}, {"allow_paid_models": True},
    {"dashscope_api_key": SecretStr("fictional-forbidden")},
    {"database_url": SecretStr("sqlite:///not-allowed.db")},
    {"database_url": SecretStr("postgresql+psycopg://rag_real:fictional@demo/rag_personal_real")},
    {"vector_uri": "/demo/milvus.db"}, {"embedding_dimension": 768},
])
def test_infrastructure_configuration_conflicts_are_rejected(changes):
    with pytest.raises(ValidationError):
        configuration(**changes)


def test_mode_is_required_in_settings():
    values = configuration().model_dump()
    values.pop("rag_runtime_mode")
    with pytest.raises(ValidationError):
        RealUsageSettings(_env_file=None, **values)


def test_loading_infrastructure_settings_never_calls_key_loader_or_dotenv(monkeypatch):
    monkeypatch.setattr(runtime, "load_key", lambda **_: pytest.fail("Key loader invoked"))
    monkeypatch.setattr("real_rag_acceptance.dotenv_values", lambda *a, **k: pytest.fail("dotenv invoked"))
    read = []
    def secret(path):
        read.append(path)
        assert path in {"/run/secrets/postgres_password", "/run/secrets/jwt_secret"}
        return "fictional-r2-secret-material-" * 2
    monkeypatch.setattr(runtime, "read_secret", secret)
    original = Path.read_text
    def text(path, *args, **kwargs):
        if path.name == ".env" or path.name == "model.env":
            pytest.fail("Model credential file read")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", text)
    cfg = runtime.load_settings("infrastructure")
    assert not cfg.dashscope_api_key.get_secret_value()
    assert len(read) == 2 and cfg.rag_runtime_mode == "infrastructure"


def test_injected_key_is_rejected_without_reading_its_value(monkeypatch):
    class Environment(dict):
        def __getitem__(self, key):
            if key == "DASHSCOPE_API_KEY":
                pytest.fail("Forbidden environment value read")
            return super().__getitem__(key)
    monkeypatch.setattr(runtime.os, "environ", Environment(DASHSCOPE_API_KEY="fictional-only"))
    with pytest.raises(runtime.Stop, match="R2_INFRASTRUCTURE_KEY_INJECTION_FORBIDDEN"):
        runtime.load_settings("infrastructure")


def test_accidental_model_secret_mount_is_rejected_without_open(monkeypatch):
    original = Path.exists
    monkeypatch.setattr(Path, "exists", lambda path: path == Path("/run/secrets/model.env") or original(path))
    monkeypatch.setattr(runtime, "load_key", lambda **_: pytest.fail("Key loader invoked"))
    with pytest.raises(runtime.Stop, match="R2_INFRASTRUCTURE_KEY_INJECTION_FORBIDDEN"):
        runtime.load_settings("infrastructure")


@pytest.mark.parametrize("mode", ["", "automatic", "mock"])
def test_cli_rejects_missing_or_invalid_mode_before_any_secret_or_database(mode, monkeypatch, capsys):
    monkeypatch.setattr(runtime.sys, "argv", ["runtime", "serve", "--runtime-mode", mode])
    monkeypatch.setattr(runtime, "load_key", lambda **_: pytest.fail("Key loader invoked"))
    monkeypatch.setattr(runtime, "read_secret", lambda *_: pytest.fail("Secret loader invoked"))
    assert runtime.main() == 2
    assert capsys.readouterr().err.strip() == "R2_RUNTIME_MODE_INVALID"


@pytest.mark.parametrize("name,value", [
    ("RAG_RUNTIME_MODE", "real"), ("MODEL_BACKEND", "qwen"), ("ALLOW_PAID_MODELS", "true")])
def test_mode_environment_conflicts_fail_closed(name, value, monkeypatch):
    monkeypatch.setenv(name, value)
    with pytest.raises(runtime.Stop, match="R2_RUNTIME_CONFIGURATION_CONFLICT"):
        runtime.load_settings("infrastructure")


def test_real_mode_still_requires_key_before_database_secrets(monkeypatch):
    def no_key(**kwargs):
        raise runtime.Stop("KEY_REQUIRED")
    monkeypatch.setattr(runtime, "load_key", no_key)
    monkeypatch.setattr(runtime, "read_secret", lambda *_: pytest.fail("Database secret read after missing key"))
    with pytest.raises(runtime.Stop, match="KEY_REQUIRED"):
        runtime.load_settings("real")
    with pytest.raises(ValidationError):
        configuration("real", dashscope_api_key=SecretStr(""))


def test_approval_is_mode_bound_and_cannot_enable_real_with_infrastructure_plan(tmp_path, monkeypatch):
    folder = tmp_path / "deploy/real-usage"
    folder.mkdir(parents=True)
    plan = {"approval_id": "fictional-infra-approval", "historical_model_requests": 6,
        "runtime_mode": "infrastructure", "paid_calls_authorized": False,
        "runtime_files": {}, "review_files": {}}
    path = folder / "approval.infrastructure.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(runtime, "ROOT", tmp_path)
    monkeypatch.setattr(preparation, "ROOT", tmp_path)
    assert runtime.check_approval(plan["approval_id"], digest, "infrastructure") == plan
    with pytest.raises(runtime.Stop, match="R2_APPROVED_RUNTIME_MODE_MISMATCH"):
        runtime.check_approval(plan["approval_id"], digest, "real", path)
    with pytest.raises(runtime.Stop, match="R1_APPROVAL_HASH_MISMATCH"):
        runtime.check_approval(plan["approval_id"], "0" * 64, "infrastructure")
    with pytest.raises(runtime.Stop, match="R1_APPROVAL_ID_OR_HISTORY_MISMATCH"):
        runtime.check_approval("different", digest, "infrastructure")
    result = preparation.check_sources("infrastructure")
    assert result["runtime_mode"] == "infrastructure" and not result["credential_contents_read"]
    assert not result["services_started"] and not result["paid_calls_authorized"]


def test_approved_cli_selects_only_declared_mode(monkeypatch):
    seen = []
    monkeypatch.setattr(runtime.sys, "argv", ["runtime", "serve", "--runtime-mode", "infrastructure",
        "--approval-id", "fictional", "--approval-sha256", "a" * 64])
    monkeypatch.setattr(runtime, "check_approval", lambda *args: {"runtime_mode": args[2]})
    monkeypatch.setattr(runtime, "serve", lambda plan, mode: seen.append((plan, mode)))
    assert runtime.main() == 0 and seen == [({"runtime_mode": "infrastructure"}, "infrastructure")]


def test_serve_wires_migration_and_health_without_executing_them(monkeypatch):
    import alembic.command
    import uvicorn
    cfg = configuration()
    monkeypatch.setattr(runtime, "load_settings", lambda mode: cfg)
    upgrade, run = Mock(), Mock()
    monkeypatch.setattr(alembic.command, "upgrade", upgrade)
    monkeypatch.setattr(uvicorn, "run", run)
    plan = {"limits": {"max_calls_total": 3, "daily_budget_cny": "0.01", "max_input_tokens": 4096}}
    runtime.serve(plan, "infrastructure")
    upgrade.assert_called_once()
    assert upgrade.call_args.args[0].attributes["settings"] is cfg
    run.assert_called_once()
    app = run.call_args.args[0]
    health = next(route for route in app.routes if getattr(route, "path", "") == "/api/health")
    data = health.endpoint()["data"]
    assert data["rag_runtime_mode"] == "infrastructure" and not data["paid_models_enabled"]
    assert run.call_args.kwargs["workers"] == 1 and not run.call_args.kwargs["access_log"]


def test_infrastructure_setup_selects_disabled_provider_and_local_vector_initialization(monkeypatch):
    cfg, setups = configuration(), []
    original = application.create_app
    def capture(settings, setup, **kwargs):
        setups.append(setup)
        return original(settings, setup=setup, **kwargs)
    monkeypatch.setattr(application, "create_app", capture)
    guard, vectors = Mock(), Mock()
    monkeypatch.setattr(application, "UsageGuard", lambda *args: guard)
    monkeypatch.setattr(application, "get_vectors", vectors)
    application.create_real_app(cfg, models_factory=lambda *args: pytest.fail("Real provider factory invoked"))
    state = SimpleNamespace(engine=Mock(), sessions=Mock())
    setups[0](state)
    assert isinstance(state.models, DisabledModels) and state.usage_guard is guard
    vectors.assert_called_once_with(state)


@pytest.mark.parametrize("method,args", [("embed", (["synthetic"],)),
    ("answer", ("question", [{"text": "evidence"}], [])), ("call", ("/embeddings", {}, "EMBEDDING_ERROR"))])
def test_disabled_provider_and_injected_fallback_cannot_claim_model_success(method, args):
    cfg = configuration()
    injected = Mock()
    state = SimpleNamespace(settings=cfg, models=injected)
    for provider in (make_models(cfg), get_models(state)):
        with pytest.raises(AppError) as error:
            getattr(provider, method)(*args)
        assert error.value.code == "MODEL_DISABLED" and error.value.status == 403
    assert not injected.mock_calls


@pytest.mark.parametrize("path", ["/embeddings", "/chat/completions"])
def test_uniform_execution_gate_blocks_before_reservation_or_transport(path):
    usage = UsageGuard.__new__(UsageGuard)
    usage.cfg = configuration()
    usage.sessions = Mock(side_effect=AssertionError("Unexpected usage database access"))
    send = Mock()
    with pytest.raises(AppError) as error:
        usage.execute(path, {}, send, "MODEL_UNAVAILABLE")
    assert error.value.code == "MODEL_DISABLED"
    usage.sessions.assert_not_called()
    send.assert_not_called()


def test_real_provider_construction_rejects_infrastructure_even_with_tampered_flags():
    cfg = configuration().model_copy(update={"model_backend": "qwen", "allow_paid_models": True,
        "dashscope_api_key": SecretStr("fictional-never-used")})
    for factory in (QwenModels, lambda c: GuardedModels(c, Mock())):
        with pytest.raises(AppError) as error:
            factory(cfg)
        assert error.value.code == "MODEL_DISABLED"


def test_background_index_job_fails_safely_without_model_or_vector_insert(monkeypatch):
    import app.services.documents as service
    cfg = configuration()
    doc = SimpleNamespace(id="synthetic-doc", status="uploaded", progress=0,
        file_path="not-opened.txt", file_type="txt", name="synthetic.txt", knowledge_base_id="synthetic-kb")
    db = MagicMock()
    db.get.return_value = doc
    sessions = MagicMock()
    sessions.return_value.__enter__.return_value = db
    vectors = Mock()
    monkeypatch.setattr(service, "parse", Mock(return_value=[]))
    monkeypatch.setattr(service, "split", Mock(return_value=[("synthetic evidence", {})]))
    monkeypatch.setattr(service, "get_vectors", lambda _: vectors)
    injected = Mock()
    state = SimpleNamespace(settings=cfg, lock=RLock(), sessions=sessions, models=injected)
    service.process_document(state, doc.id)
    assert doc.status == "failed" and doc.error_code == "MODEL_DISABLED" and doc.progress == 0
    db.add_all.assert_not_called()
    vectors.insert.assert_not_called()
    assert not injected.mock_calls


def test_real_transport_accounting_tail_is_unchanged_by_budget_updates():
    tree = ast.parse((ROOT / "backend/app/real_usage/guard.py").read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "UsageGuard")
    execute = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "execute")
    assert isinstance(execute.body[0], ast.If)
    ledger = next(node for node in ast.walk(execute) if isinstance(node, ast.With)
        and any(isinstance(stmt, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "kind_limit"
            for t in stmt.targets) for stmt in node.body))
    position = next(i for i, stmt in enumerate(ledger.body) if isinstance(stmt, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "kind_limit" for t in stmt.targets))
    assert isinstance(ledger.body[position + 1], ast.If)
    assert ast.unparse(ledger.body[position + 1].body[0]) == "blocked('USAGE_LIMIT')"
    # R4 intentionally changes reservation limits, not the send/usage/UNKNOWN tail.
    outer = next(node for node in execute.body if isinstance(node, ast.Try))
    position = next(i for i, node in enumerate(outer.body) if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute)
        and node.value.func.attr == "_audit")
    tail = ast.dump(ast.Module(body=outer.body[position:] + outer.finalbody, type_ignores=[]), include_attributes=False)
    assert hashlib.sha256(tail.encode()).hexdigest() == "bda74d8cb9faaf097b8e07fa4fa45f9d842e19e72c0937b0ec29402d46e6de8b"


def test_standalone_infrastructure_compose_has_no_model_key_injection_and_real_stays_explicit():
    infra = yaml.safe_load((ROOT / "deploy/real-usage/compose.infrastructure.yml").read_text(encoding="utf-8"))
    real = yaml.safe_load((ROOT / "deploy/real-usage/compose.yml").read_text(encoding="utf-8"))
    assert infra["name"] == real["name"] == "rag-knowledge-real"
    assert set(infra["volumes"]) == {"real_pg_data", "real_app_data", "real_audit_data"}
    assert infra["networks"] == {"default": {}}
    assert infra["services"]["real-frontend"]["ports"] == ["127.0.0.1:8081:80"]
    backend = infra["services"]["real-backend"]
    assert backend["environment"]["RAG_RUNTIME_MODE"] == "infrastructure"
    assert backend["environment"]["MODEL_BACKEND"] == "mock" and backend["environment"]["ALLOW_PAID_MODELS"] == "false"
    assert "DASHSCOPE_API_KEY" not in backend["environment"] and "env_file" not in backend
    assert backend["volumes"] == ["real_app_data:/data", "real_audit_data:/audit"]
    assert set(infra["secrets"]) == {"postgres_password", "jwt_secret"}
    assert real["services"]["real-backend"]["environment"]["RAG_RUNTIME_MODE"] == "real"
    assert real["services"]["real-backend"]["environment"]["ALLOW_PAID_MODELS"] == "true"
    assert any(isinstance(m, dict) and m.get("read_only") for m in real["services"]["real-backend"]["volumes"])


def test_infrastructure_cannot_acknowledge_real_model_pause(monkeypatch, capsys):
    monkeypatch.setattr(runtime.sys, "argv", ["runtime", "ack-stop", "--runtime-mode", "infrastructure",
        "--acknowledge-uncertain-charges"])
    monkeypatch.setattr(runtime, "check_approval", lambda *args: {})
    monkeypatch.setattr(runtime, "admin", lambda *_: pytest.fail("Model pause changed"))
    assert runtime.main() == 2
    assert capsys.readouterr().err.strip() == "R2_INFRASTRUCTURE_MODEL_ADMIN_DISABLED"


def test_explicit_real_mode_retains_safe_loader_and_all_original_limits(monkeypatch):
    loaded = []
    def key(**kwargs):
        loaded.append(kwargs)
        return "fictional-r2-real-mode-placeholder"
    monkeypatch.setattr(runtime, "load_key", key)
    monkeypatch.setattr(runtime, "read_secret", lambda path: "fictional-real-mode-secret-material-" * 2)
    cfg = runtime.load_settings("real")
    assert loaded == [{"key_env_file": Path("/run/secrets/model.env")}]
    assert cfg.rag_runtime_mode == "real" and cfg.model_backend == "qwen" and cfg.allow_paid_models
    assert cfg.max_calls_total == 3 and str(cfg.daily_budget_cny) == "0.01"
    assert cfg.max_input_tokens == 4096 and cfg.max_output_tokens == 256
    assert cfg.model_timeout_seconds == 30 and cfg.historical_model_requests == 6


def test_real_approval_requires_paid_scope_and_rejects_paths_outside_deploy(tmp_path, monkeypatch):
    folder = tmp_path / "deploy/real-usage"
    folder.mkdir(parents=True)
    path = folder / "approval.real-fictional.json"
    plan = {"approval_id": "fictional-real", "historical_model_requests": 6,
        "runtime_mode": "real", "paid_calls_authorized": True, "runtime_files": {}}
    path.write_text(json.dumps(plan), encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    monkeypatch.setattr(runtime, "ROOT", tmp_path)
    assert runtime.check_approval(plan["approval_id"], digest, "real", path) == plan
    plan["paid_calls_authorized"] = False
    path.write_text(json.dumps(plan), encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(runtime.Stop, match="R2_APPROVED_RUNTIME_MODE_MISMATCH"):
        runtime.check_approval(plan["approval_id"], digest, "real", path)
    with pytest.raises(runtime.Stop, match="R1_ARTIFACT_PATH_INVALID"):
        runtime.approval_path("infrastructure", tmp_path / "outside.json")
