from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from app.api.deps import current_user, get_db, owned_kb, owned_session
from app.core.errors import ok
from app.models import ChatSession, ChatMessage
from app.schemas import Envelope, SessionInput, SessionOut, MessageInput, MessageOut

router = APIRouter(prefix="/api/sessions")


@router.post("", response_model=Envelope[SessionOut], status_code=201)
def create_session(body: SessionInput, db=Depends(get_db), user=Depends(current_user)):
    owned_kb(db, user, body.knowledge_base_id)
    row = ChatSession(owner_id=user.id, **body.model_dump())
    db.add(row)
    db.commit()
    return ok(row)


@router.get("", response_model=Envelope[list[SessionOut]])
def list_sessions(db=Depends(get_db), user=Depends(current_user)):
    return ok(db.scalars(select(ChatSession).where(ChatSession.owner_id == user.id).order_by(ChatSession.created_at.desc())).all())


@router.get("/{session_id}", response_model=Envelope[SessionOut])
def get_session(session_id: str, db=Depends(get_db), user=Depends(current_user)):
    return ok(owned_session(db, user, session_id))


@router.delete("/{session_id}", response_model=Envelope[None])
def remove_session(session_id: str, request: Request, db=Depends(get_db), user=Depends(current_user)):
    with request.app.state.lock:
        db.delete(owned_session(db, user, session_id))
        db.commit()
    return ok()


@router.get("/{session_id}/messages", response_model=Envelope[list[MessageOut]])
def messages(session_id: str, db=Depends(get_db), user=Depends(current_user)):
    owned_session(db, user, session_id)
    return ok(db.scalars(select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at, ChatMessage.id)).all())


@router.post("/{session_id}/messages", response_model=Envelope[MessageOut])
def send(session_id: str, body: MessageInput, request: Request, db=Depends(get_db), user=Depends(current_user)):
    from app.services.chat import send_message
    with request.app.state.lock:
        session = owned_session(db, user, session_id)
        return ok(send_message(request.app.state, db, session, body.question, body.top_k))
