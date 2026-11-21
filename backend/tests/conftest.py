import pytest
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def client(tmp_path):
    cfg = Settings(database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
                   storage_dir=tmp_path / "uploads", vector_uri=str(tmp_path / "vectors.db"),
                   vector_backend="memory", model_backend="mock", allow_paid_models=False)
    with TestClient(create_app(cfg), raise_server_exceptions=False) as value:
        yield value


def login(client, username="tester"):
    client.post("/api/auth/register", json={"username": username, "password": "Test-password-123"})
    result = client.post("/api/auth/login", json={"username": username, "password": "Test-password-123"})
    return {"Authorization": "Bearer " + result.json()["data"]["access_token"]}


@pytest.fixture
def headers(client):
    return login(client)
