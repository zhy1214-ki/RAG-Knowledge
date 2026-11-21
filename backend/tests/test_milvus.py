from uuid import uuid4
from pathlib import Path
import subprocess
import sys
import pytest
from app.rag.vectors import MilvusVectors
from app.rag.providers import MockModels


@pytest.mark.infrastructure
def test_real_milvus_persistence_filter_delete(tmp_path):
    uri = str(tmp_path / "real.db")
    store = MilvusVectors(uri, "mock")
    vectors = MockModels().embed(["差旅报销政策", "服务器配置"])
    ids = [str(uuid4()), str(uuid4())]
    try:
        store.insert([{"chunk_id": ids[0], "document_id": "doc1", "knowledge_base_id": "kb1", "vector": vectors[0]},
                      {"chunk_id": ids[1], "document_id": "doc2", "knowledge_base_id": "kb2", "vector": vectors[1]}])
        hits = store.search("kb1", vectors[0], 5)
        assert len(hits) == 1 and hits[0][0] == ids[0] and hits[0][1] > .99
        assert store.search("unknown", vectors[0], 5) == []
    finally:
        store.close()
    # An entirely new interpreter must load a persisted (released) collection too.
    probe = """import sys
from app.rag.vectors import MilvusVectors
s=MilvusVectors(sys.argv[1],"mock")
try:
    assert len(s.search("kb1",[1.0]+[0.0]*1023,5))==1
finally:
    s.close()
"""
    result = subprocess.run([sys.executable, "-c", probe, uri], cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    reopened = MilvusVectors(uri, "mock")
    try:
        assert reopened.search("kb1", vectors[0], 5)[0][0] == ids[0]
        reopened.delete("doc1")
        reopened.delete("doc1")
        assert reopened.search("kb1", vectors[0], 5) == []
        assert reopened.search("kb2", vectors[1], 5)[0][0] == ids[1]
    finally:
        reopened.close()
