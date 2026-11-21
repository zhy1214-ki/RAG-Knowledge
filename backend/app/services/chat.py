from sqlalchemy import select
from app.models import DocumentChunk, Document, ChatMessage
from app.rag.providers import get_models, NO_EVIDENCE
from app.rag.vectors import get_vectors


def retrieve(state, db, kb_id, question, top_k):
    if not db.scalar(select(Document.id).where(Document.knowledge_base_id == kb_id, Document.status == "indexed").limit(1)):
        return []
    vector = get_models(state).embed([question])[0]
    hits = get_vectors(state).search(kb_id, vector, top_k)
    result = []
    for chunk_id, score in hits:
        if score < state.settings.min_score:
            continue
        chunk = db.scalar(select(DocumentChunk).join(Document, Document.id == DocumentChunk.document_id).where(
            DocumentChunk.chunk_id == chunk_id, DocumentChunk.knowledge_base_id == kb_id,
            Document.knowledge_base_id == kb_id, Document.status == "indexed"))
        if chunk:
            result.append({"source_id": len(result) + 1, "chunk_id": chunk.chunk_id, "document_id": chunk.document_id, "knowledge_base_id": kb_id,
                "source_name": chunk.source_name, "source_location": chunk.source_location, "text": chunk.text, "score": score})
    return result


def send_message(state, db, session, question, top_k):
    sources = retrieve(state, db, session.knowledge_base_id, question, top_k)
    history = list(reversed(db.scalars(select(ChatMessage).where(ChatMessage.session_id == session.id).order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc()).limit(10)).all()))
    content, ids = get_models(state).answer(question, sources, history) if sources else (NO_EVIDENCE, [])
    citations = [sources[i - 1] for i in ids]
    user_message = ChatMessage(session_id=session.id, role="user", content=question, citations=[])
    answer = ChatMessage(session_id=session.id, role="assistant", content=content, citations=citations)
    db.add(user_message)
    db.flush()
    db.add(answer)
    if session.title == "新会话":
        session.title = question[:120]
    # Persist both messages together only after successful generation and citation validation.
    db.commit()
    return answer
