import json
import httpx
from fastapi.testclient import TestClient
from pydantic import SecretStr
from app.factory import create_app
from app.core.config import Settings
from app.rag.providers import MockModels
from app.real_usage.application import create_real_app
from app.real_usage.models import GuardedModels


def create_fixture_app(settings, tmp_path, fail=False, max_chunks=32):
    cfg = settings.model_copy(update={"database_url": SecretStr("sqlite:///" + (tmp_path / "app.db").as_posix()),
        "storage_dir": tmp_path / "uploads", "vector_uri": str(tmp_path / "unused.db"),
        "vector_backend": "memory", "max_document_chunks": max_chunks})
    sent = []
    def factory(cfg, guard):
        def wire(request):
            sent.append(request.url.path)
            if fail: raise httpx.ReadTimeout("offline timeout")
            body = json.loads(request.content)
            if request.url.path.endswith("/embeddings"):
                vectors = MockModels().embed(body["input"])
                return httpx.Response(200, json={"usage":{"prompt_tokens":sum(len(t.encode()) for t in body["input"])},
                    "data":[{"index":i,"embedding":v} for i,v in enumerate(vectors)]})
            return httpx.Response(200, json={"usage":{"prompt_tokens":20,"completion_tokens":12},
                "choices":[{"finish_reason":"stop","message":{"content":'{"answer":"17 days [1]","source_ids":[1]}'}}]})
        def client(**kwargs):
            kwargs.pop("transport").close()
            return httpx.Client(transport=httpx.MockTransport(wire), **kwargs)
        return GuardedModels(cfg, guard, client)
    return create_real_app(cfg, factory), sent


def login(client):
    body={"username":"r1_offline","password":"offline-test-passphrase"}
    assert client.post("/api/auth/register",json=body).status_code==201
    response=client.post("/api/auth/login",json=body)
    assert response.status_code==200
    return {"Authorization":"Bearer "+response.json()["data"]["access_token"]}


def test_isolated_api_flow_duplicate_gate_and_sqlite_history_restart(settings,tmp_path):
    app,sent=create_fixture_app(settings,tmp_path)
    with TestClient(app) as client:
        headers=login(client)
        schema=client.get("/openapi.json").json()
        assert sum(method in ["get","post","put","delete"] for methods in schema["paths"].values() for method in methods)==20
        kb=client.post("/api/knowledge-bases",json={"name":"R1 synthetic"},headers=headers).json()["data"]["id"]
        path="/api/knowledge-bases/"+kb+"/documents"
        file=("policy.txt",b"Synthetic policy: the return period is 17 days.","text/plain")
        uploaded=client.post(path,files={"file":file},headers=headers)
        assert uploaded.status_code==202
        rows=client.get(path,headers=headers).json()["data"]
        assert len(rows)==1 and rows[0]["status"]=="indexed"
        duplicate=client.post(path,files={"file":file},headers=headers)
        assert duplicate.status_code==409 and duplicate.json()["code"]=="DUPLICATE_REQUEST"
        session=client.post("/api/sessions",json={"knowledge_base_id":kb},headers=headers).json()["data"]["id"]
        messages="/api/sessions/"+session+"/messages"
        body={"question":"Synthetic policy return period"}
        response=client.post(messages,json=body,headers=headers)
        assert response.status_code==200 and response.json()["data"]["citations"][0]["document_id"]==rows[0]["id"]
        assert client.post(messages,json=body,headers=headers).json()["code"]=="DUPLICATE_REQUEST"
        assert len(client.get(messages,headers=headers).json()["data"])==2
        limited=client.post("/api/knowledge-bases/"+kb+"/search",json={"question":"another synthetic policy"},headers=headers)
        assert limited.status_code==429 and limited.json()["code"]=="USAGE_LIMIT"
        assert len(sent)==3 and app.state.usage_guard.summary()["r1_reserved_attempts"]==3
    restored,_=create_fixture_app(settings,tmp_path)
    with TestClient(restored) as client:
        assert len(client.get(messages,headers=headers).json()["data"])==2
        assert client.get(path,headers=headers).json()["data"][0]["status"]=="indexed"
        assert restored.state.usage_guard.summary()["r1_reserved_attempts"]==3


def test_indexing_timeout_records_failed_and_blocks_duplicate_paid_work(settings,tmp_path):
    app,sent=create_fixture_app(settings,tmp_path,fail=True)
    with TestClient(app) as client:
        headers=login(client)
        kb=client.post("/api/knowledge-bases",json={"name":"R1 failing synthetic"},headers=headers).json()["data"]["id"]
        path="/api/knowledge-bases/"+kb+"/documents"
        assert client.post(path,files={"file":("failed.txt",b"synthetic policy","text/plain")},headers=headers).status_code==202
        row=client.get(path,headers=headers).json()["data"][0]
        assert row["status"]=="failed" and row["error_code"]=="EMBEDDING_ERROR"
        assert app.state.usage_guard.summary()["stopped"] and len(sent)==1


def test_document_chunk_limit_blocks_before_any_model_request(settings,tmp_path,monkeypatch):
    import app.services.documents as service
    monkeypatch.setattr(service,"split",lambda *args:[("first",{}),("second",{})])
    app,sent=create_fixture_app(settings,tmp_path,max_chunks=1)
    with TestClient(app) as client:
        headers=login(client)
        kb=client.post("/api/knowledge-bases",json={"name":"R1 chunk limit"},headers=headers).json()["data"]["id"]
        path="/api/knowledge-bases/"+kb+"/documents"
        assert client.post(path,files={"file":("sample.txt",b"synthetic","text/plain")},headers=headers).status_code==202
        assert client.get(path,headers=headers).json()["data"][0]["error_code"]=="DOCUMENT_LIMIT"
        assert not sent


def test_shared_factory_keeps_mock_default_without_key_files(tmp_path):
    cfg=Settings(_env_file=None,database_url=SecretStr("sqlite:///"+(tmp_path/"mock.db").as_posix()),
        storage_dir=tmp_path/"uploads",vector_backend="memory",model_backend="mock",allow_paid_models=False,
        dashscope_api_key=SecretStr(""))
    with TestClient(create_app(cfg)) as client:
        assert client.get("/api/health").json()["data"]["model_backend"]=="mock"
        assert not hasattr(client.app.state,"usage_guard")
def test_r1_guarded_routes_preserve_owner_checks_before_any_model(settings,tmp_path):
    app,sent=create_fixture_app(settings,tmp_path)
    with TestClient(app) as client:
        owner=login(client)
        kb=client.post("/api/knowledge-bases",json={"name":"owned R1"},headers=owner).json()["data"]["id"]
        session=client.post("/api/sessions",json={"knowledge_base_id":kb},headers=owner).json()["data"]["id"]
        body={"username":"r1_other","password":"offline-other-passphrase"}
        assert client.post("/api/auth/register",json=body).status_code==201
        response=client.post("/api/auth/login",json=body)
        other={"Authorization":"Bearer "+response.json()["data"]["access_token"]}
        assert client.post("/api/knowledge-bases/"+kb+"/documents",files={"file":("sample.txt",b"fictional","text/plain")},headers=other).status_code==404
        assert client.post("/api/knowledge-bases/"+kb+"/search",json={"question":"synthetic"},headers=other).status_code==404
        assert client.post("/api/sessions/"+session+"/messages",json={"question":"synthetic"},headers=other).status_code==404
        assert not sent and app.state.usage_guard.summary()["r1_reserved_attempts"]==0


def test_real_startup_exception_does_not_render_original_details(settings,tmp_path,monkeypatch):
    import traceback
    import app.factory
    import pytest
    def fail(*args):raise RuntimeError("private-diagnostic-marker")
    monkeypatch.setattr(app.factory,"make_database",fail)
    app,_=create_fixture_app(settings,tmp_path)
    with pytest.raises(RuntimeError) as exc:
        with TestClient(app):pass
    assert str(exc.value)=="R1_RUNTIME_INITIALIZATION_OR_SHUTDOWN_FAILED"
    assert "private-diagnostic-marker" not in "".join(traceback.format_exception(exc.value))

def test_upload_size_limit_is_checked_before_model_reservation(settings,tmp_path):
    app_settings = settings.model_copy(update={"max_upload_bytes":8})
    app,sent=create_fixture_app(app_settings,tmp_path)
    with TestClient(app) as client:
        headers=login(client)
        kb=client.post("/api/knowledge-bases",json={"name":"bounded upload"},headers=headers).json()["data"]["id"]
        response=client.post("/api/knowledge-bases/"+kb+"/documents",files={"file":("large.txt",b"longer-than-eight-bytes","text/plain")},headers=headers)
        assert response.status_code==413 and not sent
        assert app.state.usage_guard.summary()["r1_reserved_attempts"]==0
