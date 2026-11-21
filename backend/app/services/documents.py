from pathlib import Path
from uuid import uuid4
from sqlalchemy import select, delete
from app.core.errors import AppError
from app.models import Document, DocumentChunk
from app.rag.parsing import parse, split
from app.rag.providers import get_models
from app.rag.vectors import get_vectors


def process_document(state, document_id):
    # Background exceptions happen after the HTTP response. Never let raw errors reach Uvicorn.
    try:
        _process_document(state, document_id)
    except Exception:
        import logging
        logging.getLogger("rag.errors").warning("event=BACKGROUND_ERROR")
        try:
            with state.sessions() as db:
                doc = db.get(Document, document_id)
                if doc and doc.status in {"uploaded", "processing"}:
                    doc.status, doc.error_code, doc.progress = "failed", "INTERNAL_ERROR", 0
                    db.commit()
        except Exception:
            logging.getLogger("rag.errors").warning("event=STATE_UPDATE_ERROR")


def _process_document(state, document_id):
    # Single worker + process-local lock keeps index/delete transitions serial.
    with state.lock, state.sessions() as db:
        doc = db.get(Document, document_id)
        if not doc or doc.status != "uploaded":
            return
        try:
            doc.status, doc.progress = "processing", 10
            db.commit()
            parts = split(parse(doc.file_path, doc.file_type), state.settings.chunk_size, state.settings.chunk_overlap)
            limit = getattr(state.settings, "max_document_chunks", 0)
            if limit and len(parts) > limit:
                raise AppError("DOCUMENT_LIMIT", "文档片段超过本环境允许上限", 422)
            doc.progress = 40
            db.commit()
            vectors = get_models(state).embed([text for text, _ in parts])
            chunks = [DocumentChunk(chunk_id=str(uuid4()), document_id=doc.id, knowledge_base_id=doc.knowledge_base_id,
                text=text, source_name=doc.name, source_location=loc, chunk_index=i) for i, (text, loc) in enumerate(parts)]
            get_vectors(state).insert([{"chunk_id": c.chunk_id, "document_id": doc.id,
                "knowledge_base_id": doc.knowledge_base_id, "vector": vector} for c, vector in zip(chunks, vectors)])
            db.add_all(chunks)
            doc.status, doc.progress, doc.chunk_count, doc.error_code = "indexed", 100, len(chunks), None
            db.commit()
        except Exception as error:
            db.rollback()
            code = error.code if isinstance(error, AppError) else "INTERNAL_ERROR"
            # Index cleanup is idempotent; failed/deleting documents are never searchable.
            try:
                get_vectors(state).delete(document_id)
            except AppError:
                pass
            doc = db.get(Document, document_id)
            if doc:
                doc.status, doc.error_code, doc.progress = "failed", code, 0
                db.commit()


def delete_document(state, db, doc):
    # Persist a tombstone before touching Milvus. On failure, metadata remains retryable.
    doc.status = "deleting"
    db.commit()
    get_vectors(state).delete(doc.id)
    db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))
    file_path = Path(doc.file_path)
    file_path.unlink(missing_ok=True)
    db.delete(doc)
    db.commit()


def delete_knowledge_base(state, db, kb):
    for doc in db.scalars(select(Document).where(Document.knowledge_base_id == kb.id)).all():
        delete_document(state, db, doc)
    db.delete(kb)
    db.commit()
