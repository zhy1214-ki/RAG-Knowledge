from fastapi import Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
import jwt
from app.models import User, KnowledgeBase, Document, ChatSession
from app.core.errors import AppError

bearer = HTTPBearer(auto_error=False)


def get_db(request: Request):
    with request.app.state.sessions() as db:
        try:
            yield db
        except Exception:
            db.rollback()
            raise


def current_user(request: Request, token: HTTPAuthorizationCredentials | None = Depends(bearer), db=Depends(get_db)):
    try:
        claims = jwt.decode(token.credentials, request.app.state.settings.jwt_secret.get_secret_value(), algorithms=["HS256"])
        user = db.get(User, claims["sub"])
        if not user:
            raise ValueError()
        return user
    except (AttributeError, KeyError, ValueError, jwt.PyJWTError):
        raise AppError("UNAUTHORIZED", "请先登录", 401) from None


def owned_kb(db, user, kb_id):
    row = db.scalar(select(KnowledgeBase).where(KnowledgeBase.id == kb_id, KnowledgeBase.owner_id == user.id))
    if not row:
        raise AppError("NOT_FOUND", "知识库不存在", 404)
    return row


def owned_document(db, user, kb_id, doc_id):
    owned_kb(db, user, kb_id)
    row = db.scalar(select(Document).where(Document.id == doc_id, Document.knowledge_base_id == kb_id))
    if not row:
        raise AppError("NOT_FOUND", "文档不存在", 404)
    return row


def owned_session(db, user, session_id):
    row = db.scalar(select(ChatSession).where(ChatSession.id == session_id, ChatSession.owner_id == user.id))
    if not row:
        raise AppError("NOT_FOUND", "会话不存在", 404)
    owned_kb(db, user, row.knowledge_base_id)
    return row
