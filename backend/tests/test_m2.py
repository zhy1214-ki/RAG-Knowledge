from io import BytesIO
import pytest
import pymupdf
from docx import Document as WordDocument
from app.core.errors import AppError
from app.models import Document, DocumentChunk
from app.rag.providers import MockModels
from sqlalchemy import select
from conftest import login


def create_kb(client, headers, name="研发手册"):
    return client.post("/api/knowledge-bases", headers=headers, json={"name": name}).json()["data"]["id"]


def upload(client, headers, kb, filename="guide.txt", data=None):
    return client.post(f"/api/knowledge-bases/{kb}/documents", headers=headers,
        files={"file": (filename, data if data is not None else "报销政策：差旅报销需在三十天内提交审批。".encode())})


def test_upload_chunk_search_delete(client, headers):
    kb = create_kb(client, headers)
    response = upload(client, headers, kb)
    assert response.status_code == 202
    doc = response.json()["data"]["id"]
    state = client.get(f"/api/knowledge-bases/{kb}/documents/{doc}", headers=headers).json()["data"]
    assert state["status"] == "indexed" and state["progress"] == 100 and state["chunk_count"] > 0
    hits = client.post(f"/api/knowledge-bases/{kb}/search", headers=headers, json={"question": "报销政策"}).json()["data"]
    assert hits and hits[0]["document_id"] == doc and "三十天" in hits[0]["text"]
    assert "page" not in hits[0]["source_location"]
    assert client.delete(f"/api/knowledge-bases/{kb}/documents/{doc}", headers=headers).status_code == 200
    assert client.post(f"/api/knowledge-bases/{kb}/search", headers=headers, json={"question":"报销政策"}).json()["data"] == []
    with client.app.state.sessions() as db:
        assert db.scalar(select(DocumentChunk).where(DocumentChunk.document_id == doc)) is None


@pytest.mark.parametrize("kind", ["pdf", "docx", "md"])
def test_document_formats(client, headers, kind):
    kb = create_kb(client, headers)
    if kind == "pdf":
        pdf = pymupdf.open()
        pdf.new_page().insert_text((72, 72), "First page: travel policy.")
        pdf.new_page().insert_text((72, 72), "Second page: reimbursement in thirty days.")
        raw = pdf.tobytes()
        pdf.close()
    elif kind == "docx":
        doc = WordDocument()
        doc.add_paragraph("报销政策：三十天内提交审批。")
        buf = BytesIO(); doc.save(buf); raw = buf.getvalue()
    else:
        raw = "# 报销政策\n三十天内提交审批。".encode()
    response = upload(client, headers, kb, "guide."+kind, raw)
    doc_id = response.json()["data"]["id"]
    assert client.get(f"/api/knowledge-bases/{kb}/documents/{doc_id}", headers=headers).json()["data"]["status"] == "indexed"
    with client.app.state.sessions() as db:
        chunks = db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == doc_id)).all()
        if kind == "pdf":
            assert {c.source_location["page"] for c in chunks} == {1, 2}
        else:
            assert all("page" not in c.source_location for c in chunks)


def test_upload_failures(client, headers):
    kb = create_kb(client, headers)
    assert upload(client, headers, kb, "unsafe.exe").status_code == 415
    assert upload(client, headers, kb, "empty.txt", b"").status_code == 422
    client.app.state.settings.max_upload_bytes = 10
    assert upload(client, headers, kb, "large.txt", b"x"*11).status_code == 413
    client.app.state.settings.max_upload_bytes = 10000
    row = upload(client, headers, kb, "bad.pdf", b"not a pdf").json()["data"]
    status = client.get(f"/api/knowledge-bases/{kb}/documents/{row['id']}", headers=headers).json()["data"]
    assert status["status"] == "failed" and status["error_code"] == "PARSE_ERROR"
    assert "file_path" not in status


def test_embedding_failure_and_redaction(client, headers, monkeypatch):
    kb = create_kb(client, headers)
    def fail(*_):
        raise AppError("EMBEDDING_ERROR", "Embedding 暂不可用", 503)
    monkeypatch.setattr(MockModels, "embed", fail)
    doc = upload(client, headers, kb).json()["data"]["id"]
    row = client.get(f"/api/knowledge-bases/{kb}/documents/{doc}", headers=headers).json()["data"]
    assert row["status"] == "failed" and row["error_code"] == "EMBEDDING_ERROR"


def test_scope_and_delete_failure(client, headers, monkeypatch):
    kb = create_kb(client, headers)
    kb2 = create_kb(client, headers, "另一个")
    doc = upload(client, headers, kb).json()["data"]["id"]
    other = login(client, "another")
    assert client.get(f"/api/knowledge-bases/{kb}/documents", headers=other).status_code == 404
    assert client.get(f"/api/knowledge-bases/{kb2}/documents/{doc}", headers=headers).status_code == 404
    assert client.post(f"/api/knowledge-bases/{kb2}/search", headers=headers, json={"question":"报销政策"}).json()["data"] == []
    store = client.app.state.vectors
    real_delete = store.delete
    def fail(*_):
        raise AppError("VECTOR_ERROR", "清理失败", 503)
    monkeypatch.setattr(store, "delete", fail)
    assert client.delete(f"/api/knowledge-bases/{kb}/documents/{doc}", headers=headers).status_code == 503
    assert client.get(f"/api/knowledge-bases/{kb}/documents/{doc}", headers=headers).json()["data"]["status"] == "deleting"
    assert client.post(f"/api/knowledge-bases/{kb}/search", headers=headers, json={"question":"报销政策"}).json()["data"] == []
    monkeypatch.setattr(store, "delete", real_delete)
    assert client.delete(f"/api/knowledge-bases/{kb}/documents/{doc}", headers=headers).status_code == 200


def test_mock_embedding_deterministic():
    model=MockModels()
    first, second=model.embed(["差旅报销", "服务器配置"])
    assert len(first)==1024 and first==model.embed(["差旅报销"])[0]
    assert sum(x*x for x in first)==pytest.approx(1)
    assert sum(a*b for a,b in zip(first,second)) < .5
