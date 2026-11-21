import json
import logging
from pathlib import Path
from app.core.errors import AppError


class MemoryVectors:
    """Offline test double only. The application default is persistent Milvus Lite."""
    def __init__(self):
        self.rows = {}

    def insert(self, rows):
        for row in rows:
            self.rows[row["chunk_id"]] = row

    def search(self, kb_id, vector, top_k):
        results = [(r["chunk_id"], sum(a*b for a,b in zip(r["vector"], vector))) for r in self.rows.values() if r["knowledge_base_id"] == kb_id]
        return sorted(results, key=lambda r: r[1], reverse=True)[:top_k]

    def delete(self, document_id):
        self.rows = {k: v for k,v in self.rows.items() if v["document_id"] != document_id}

    def close(self):
        pass


class MilvusVectors:
    def __init__(self, uri, mode):
        self.collection = "rag_" + mode + "_1024_v1"
        self.uri = str(Path(uri).resolve())
        for name in ("pymilvus", "milvus_lite", "grpc._server"):
            logger = logging.getLogger(name)
            logger.handlers = [logging.NullHandler()]
            logger.propagate = False
        try:
            from pymilvus import MilvusClient
            # Vendor diagnostics may contain query metadata; keep them out of app logs.
            for name in list(logging.Logger.manager.loggerDict):
                if name.startswith(("pymilvus", "milvus_lite")):
                    logger = logging.getLogger(name)
                    logger.handlers = [logging.NullHandler()]
                    logger.propagate = False
            Path(uri).parent.mkdir(parents=True, exist_ok=True)
            self.client = MilvusClient(uri=self.uri)
            if not self.client.has_collection(self.collection):
                self.client.create_collection(collection_name=self.collection, dimension=1024,
                    primary_field_name="chunk_id", id_type="string", max_length=36,
                    auto_id=False, metric_type="COSINE", enable_dynamic_field=True)
            self.client.load_collection(collection_name=self.collection)
        except Exception:
            raise AppError("VECTOR_ERROR", "向量数据库初始化失败", 503) from None

    def insert(self, rows):
        try:
            # Batch keeps indexing memory bounded for demo-scale files.
            for offset in range(0, len(rows), 100):
                self.client.insert(collection_name=self.collection, data=rows[offset:offset+100])
        except Exception:
            raise AppError("VECTOR_ERROR", "向量索引写入失败", 503) from None

    def search(self, kb_id, vector, top_k):
        try:
            hits = self.client.search(collection_name=self.collection, data=[vector], limit=top_k,
                filter="knowledge_base_id == " + json.dumps(kb_id),
                output_fields=["chunk_id"], search_params={"metric_type": "COSINE"})
            return [(str(h["chunk_id"]), float(h["distance"])) for h in hits[0]]
        except Exception:
            raise AppError("VECTOR_ERROR", "向量检索失败", 503) from None

    def delete(self, document_id):
        try:
            self.client.delete(collection_name=self.collection, filter="document_id == " + json.dumps(document_id))
        except Exception:
            raise AppError("VECTOR_ERROR", "向量索引清理失败，请重试删除", 503) from None

    def close(self):
        self.client.close()
        from milvus_lite.server_manager import server_manager_instance
        server_manager_instance.release_server(self.uri)


def get_vectors(state):
    if not getattr(state, "vectors", None):
        cfg = state.settings
        state.vectors = MemoryVectors() if cfg.vector_backend == "memory" else MilvusVectors(cfg.vector_uri, cfg.model_backend)
    return state.vectors
