import pytest
from pydantic import ValidationError
from app.core.config import Settings
from app.core.errors import AppError
from app.rag.providers import MockModels, QwenModels, NO_EVIDENCE, SYSTEM_PROMPT
from conftest import login
from test_m2 import create_kb, upload


def new_session(client, headers, kb):
    result = client.post("/api/sessions", headers=headers, json={"knowledge_base_id": kb})
    assert result.status_code == 201
    return result.json()["data"]["id"]


def test_rag_citations_and_history(client, headers):
    kb = create_kb(client, headers)
    doc = upload(client, headers, kb).json()["data"]["id"]
    session = new_session(client, headers, kb)
    response = client.post(f"/api/sessions/{session}/messages", headers=headers, json={"question":"报销政策"})
    assert response.status_code == 200
    answer = response.json()["data"]
    assert "三十天" in answer["content"] and "离线演示" in answer["content"]
    assert answer["citations"][0]["document_id"] == doc
    assert answer["citations"][0]["source_name"] == "guide.txt"
    assert "page" not in answer["citations"][0]["source_location"]
    history = client.get(f"/api/sessions/{session}/messages", headers=headers).json()["data"]
    assert [r["role"] for r in history] == ["user","assistant"]
    assert history[-1]["citations"] == answer["citations"]


def test_no_evidence_no_generation(client, headers, monkeypatch):
    kb=create_kb(client, headers)
    session=new_session(client, headers, kb)
    def fail(*_):
        raise AssertionError("Generation must not run without evidence")
    monkeypatch.setattr(MockModels,"answer",fail)
    answer=client.post(f"/api/sessions/{session}/messages",headers=headers,json={"question":"没有上传文档"}).json()["data"]
    assert answer["content"]==NO_EVIDENCE and answer["citations"]==[]


def test_model_failure_atomic_and_session_scope(client, headers, monkeypatch):
    kb=create_kb(client, headers)
    upload(client, headers,kb)
    session=new_session(client, headers,kb)
    def fail(*_):
        raise AppError("MODEL_UNAVAILABLE","模型服务不可用",503)
    monkeypatch.setattr(MockModels,"answer",fail)
    assert client.post(f"/api/sessions/{session}/messages",headers=headers,json={"question":"报销政策"}).status_code==503
    assert client.get(f"/api/sessions/{session}/messages",headers=headers).json()["data"]==[]
    other=login(client,"outsider")
    for suffix in ("","/messages"):
        assert client.get(f"/api/sessions/{session}{suffix}",headers=other).status_code==404
    assert client.post(f"/api/sessions/{session}/messages",headers=other,json={"question":"报销"}).status_code==404
    assert client.delete(f"/api/sessions/{session}",headers=other).status_code==404
    assert client.delete(f"/api/sessions/{session}",headers=headers).status_code==200


def test_real_provider_requires_opt_in():
    with pytest.raises(ValidationError):
        Settings(model_backend="qwen",allow_paid_models=False,dashscope_api_key="synthetic-not-a-real-key")
    assert "不可信" in SYSTEM_PROMPT and "不执行" in SYSTEM_PROMPT


@pytest.mark.parametrize("payload",[
    {"answer":"捏造 [99]","source_ids":[99]},
    {"answer":"伪造 [2]","source_ids":[1]},
    {"answer":"回答","source_ids":["1"]},
])
def test_qwen_adapter_rejects_fake_citations(monkeypatch,payload):
    import json
    cfg=Settings(model_backend="qwen",allow_paid_models=True,dashscope_api_key="synthetic-not-a-real-key")
    model=QwenModels(cfg)
    monkeypatch.setattr(model,"call",lambda *_:{"choices":[{"message":{"content":json.dumps(payload)}}]})
    with pytest.raises(AppError) as exc:
        model.answer("问题",[{"text":"证据"}],[])
    assert exc.value.code=="MODEL_UNAVAILABLE"


def test_qwen_embedding_batches_and_validates(monkeypatch):
    cfg=Settings(model_backend="qwen",allow_paid_models=True,dashscope_api_key="synthetic-not-a-real-key")
    model=QwenModels(cfg)
    sizes=[]
    def fake(path, body, code):
        sizes.append(len(body["input"]))
        assert body["dimensions"]==1024
        return {"data":[{"index":i,"embedding":[0.1]*1024} for i in range(len(body["input"]))]}
    monkeypatch.setattr(model,"call",fake)
    assert len(model.embed(["synthetic"]*21))==21 and sizes==[10,10,1]


def test_selected_citation_keeps_source_number(client,headers,monkeypatch):
    kb=create_kb(client,headers)
    upload(client,headers,kb,"one.txt","报销政策：差旅报销三十天内提交。".encode())
    upload(client,headers,kb,"two.txt","报销政策：差旅报销需要发票和审批单。".encode())
    session=new_session(client,headers,kb)
    monkeypatch.setattr(MockModels,"answer",lambda *_:("参考第二份证据 [2]",[2]))
    response=client.post(f"/api/sessions/{session}/messages",headers=headers,json={"question":"报销政策"})
    assert response.status_code==200
    citations=response.json()["data"]["citations"]
    assert len(citations)==1 and citations[0]["source_id"]==2
