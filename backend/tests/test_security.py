import logging
import pytest
import httpx
from sqlalchemy.exc import SQLAlchemyError
from app.rag.providers import QwenModels
from app.core.config import Settings
from app.core.errors import AppError
from conftest import login
from test_m2 import create_kb, upload


@pytest.mark.parametrize("exception,code",[
    (RuntimeError("secret-password document-body Authorization: Bearer synthetic-key"),"INTERNAL_ERROR"),
    (SQLAlchemyError("postgresql://user:secret-password@host/db"),"DATABASE_ERROR")
])
def test_unhandled_errors_are_redacted(client, caplog, exception, code):
    @client.app.get("/test-error")
    def error():
        raise exception
    with caplog.at_level(logging.WARNING):
        response=client.get("/test-error")
    assert response.json()["code"]==code
    output=response.text+caplog.text
    assert "secret-password" not in output and "synthetic-key" not in output and "document-body" not in output
    assert response.json()["request_id"]


def test_credentials_not_returned(client, headers):
    assert "password" not in client.get("/api/auth/me",headers=headers).text
    bad=client.post("/api/auth/register",json={"username":"bad","password":"secret"})
    assert bad.status_code==422 and "secret" not in bad.text
    assert client.post("/api/auth/login",json={"username":"missing","password":"secret-test-123"}).status_code==401


def test_kb_cascade_cleans_files_vectors_sessions(client,headers):
    kb=create_kb(client,headers)
    doc=upload(client,headers,kb).json()["data"]["id"]
    session=client.post("/api/sessions",headers=headers,json={"knowledge_base_id":kb}).json()["data"]["id"]
    client.post(f"/api/sessions/{session}/messages",headers=headers,json={"question":"报销政策"})
    assert client.delete(f"/api/knowledge-bases/{kb}",headers=headers).status_code==200
    assert client.get(f"/api/sessions/{session}",headers=headers).status_code==404
    assert not list(client.app.state.settings.storage_dir.iterdir())
    assert all(v["document_id"]!=doc for v in client.app.state.vectors.rows.values())


def test_upstream_error_classification(monkeypatch,caplog):
    cfg=Settings(model_backend="qwen",allow_paid_models=True,dashscope_api_key="synthetic-not-a-real-key")
    model=QwenModels(cfg)
    transport=httpx.MockTransport(lambda request:httpx.Response(500,json={"error":"synthetic-key secret-password document-body"}))
    real_client=httpx.Client
    monkeypatch.setattr(httpx,"Client",lambda **kwargs:real_client(transport=transport))
    with pytest.raises(AppError) as exc:
        model.embed(["synthetic"])
    assert exc.value.code=="EMBEDDING_ERROR"
    assert "synthetic-key" not in str(exc.value)+caplog.text


def test_background_unknown_error_records_failed(client,headers,monkeypatch,caplog):
    from app.services import documents
    kb=create_kb(client,headers)
    def fail(*_):
        raise RuntimeError("secret-document-body")
    monkeypatch.setattr(documents,"_process_document",fail)
    doc=upload(client,headers,kb).json()["data"]["id"]
    row=client.get(f"/api/knowledge-bases/{kb}/documents/{doc}",headers=headers).json()["data"]
    assert row["status"]=="failed" and row["error_code"]=="INTERNAL_ERROR"
    assert "secret-document-body" not in caplog.text
