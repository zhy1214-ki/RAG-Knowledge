import os
from io import BytesIO
from pathlib import Path
from uuid import uuid4
import pytest
import pymupdf
from docx import Document as WordDocument
from alembic.config import Config
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import select, inspect
from app.core.config import Settings
from app.main import create_app
from app.models import User, DocumentChunk, ChatMessage
from conftest import login

@pytest.mark.infrastructure
def test_postgres_migration_real_rag_and_cleanup(tmp_path,monkeypatch):
    url=os.getenv("TEST_POSTGRES_URL")
    if not url:
        pytest.skip("TEST_POSTGRES_URL must point to project-owned test database")
    from sqlalchemy.engine import make_url
    assert make_url(url).database == "rag_test", "Use only the dedicated rag_test database"
    monkeypatch.setenv("DATABASE_URL",url)
    config=Config(str(Path(__file__).resolve().parents[1]/"alembic.ini"))
    command.upgrade(config,"head")
    command.check(config)
    cfg=Settings(database_url=url,storage_dir=tmp_path/"uploads",vector_uri=str(tmp_path/"real.db"),vector_backend="milvus",model_backend="mock")
    username="pg_"+uuid4().hex[:12]
    kb=None
    with TestClient(create_app(cfg),raise_server_exceptions=False) as client:
        headers=login(client,username)
        try:
            kb=client.post("/api/knowledge-bases",headers=headers,json={"name":"PostgreSQL 验收"}).json()["data"]["id"]
            doc=WordDocument();doc.add_paragraph("差旅报销需在三十天内提交审批。")
            data=BytesIO();doc.save(data)
            result=client.post(f"/api/knowledge-bases/{kb}/documents",headers=headers,files={"file":("policy.docx",data.getvalue())})
            assert result.status_code==202
            document_id=result.json()["data"]["id"]
            status=client.get(f"/api/knowledge-bases/{kb}/documents/{document_id}",headers=headers).json()["data"]
            assert status["status"]=="indexed" and status["chunk_count"]>0
            pdf=pymupdf.open();pdf.new_page().insert_text((72,72),"Travel reimbursement policy: submit in thirty days.")
            raw=pdf.tobytes();pdf.close()
            pdf_id=client.post(f"/api/knowledge-bases/{kb}/documents",headers=headers,files={"file":("policy.pdf",raw)}).json()["data"]["id"]
            assert client.get(f"/api/knowledge-bases/{kb}/documents/{pdf_id}",headers=headers).json()["data"]["status"]=="indexed"
            session=client.post("/api/sessions",headers=headers,json={"knowledge_base_id":kb}).json()["data"]["id"]
            answer=client.post(f"/api/sessions/{session}/messages",headers=headers,json={"question":"差旅报销"}).json()["data"]
            assert answer["citations"] and any(s["document_id"]==document_id for s in answer["citations"])
            assert "三十天" in answer["content"]
            assert len(client.get(f"/api/sessions/{session}/messages",headers=headers).json()["data"])==2
            assert client.delete(f"/api/knowledge-bases/{kb}/documents/{document_id}",headers=headers).status_code==200
            hits=client.post(f"/api/knowledge-bases/{kb}/search",headers=headers,json={"question":"差旅报销"}).json()["data"]
            assert all(h["document_id"]!=document_id for h in hits)
            assert client.delete(f"/api/knowledge-bases/{kb}",headers=headers).status_code==200
            assert client.get(f"/api/sessions/{session}",headers=headers).status_code==404
            with client.app.state.sessions() as db:
                assert db.scalar(select(DocumentChunk).where(DocumentChunk.knowledge_base_id==kb)) is None
                assert db.scalar(select(ChatMessage).where(ChatMessage.session_id==session)) is None
                tables=inspect(client.app.state.engine).get_table_names()
                assert "alembic_version" in tables
            assert not list(cfg.storage_dir.iterdir())
        finally:
            if kb:
                client.delete(f"/api/knowledge-bases/{kb}",headers=headers)
            with client.app.state.sessions() as db:
                user=db.scalar(select(User).where(User.username==username))
                if user:
                    db.delete(user);db.commit()
