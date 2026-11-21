import sys
from pathlib import Path
from decimal import Decimal
import httpx
import pytest
from pydantic import SecretStr
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))
from app.core.db import make_database
from app.real_usage.config import RealUsageSettings
from app.real_usage.guard import UsageGuard


@pytest.fixture(autouse=True)
def no_live_http(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("R1_OFFLINE_LIVE_HTTP_FORBIDDEN")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", denied)


@pytest.fixture
def settings(tmp_path):
    cfg = RealUsageSettings(_env_file=None, rag_runtime_mode="real",
        database_url=SecretStr("postgresql+psycopg://rag_real:offline@real-postgres/rag_personal_real"),
        jwt_secret=SecretStr("r1-offline-signing-material-" * 2),
        dashscope_api_key=SecretStr("r1-offline-placeholder"))
    return cfg.model_copy(update={"audit_dir": tmp_path / "audit"})


@pytest.fixture
def guard(settings, tmp_path):
    engine, sessions = make_database("sqlite:///" + (tmp_path / "guard.db").as_posix())
    clock = [1800000000.0]
    usage = UsageGuard(engine, sessions, settings, clock=lambda: clock[0])
    yield usage, clock, engine, sessions
    engine.dispose()