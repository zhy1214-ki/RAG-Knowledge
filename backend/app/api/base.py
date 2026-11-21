import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
import jwt
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.api.deps import current_user, get_db, owned_kb
from app.core.errors import AppError, ok
from app.models import User, KnowledgeBase
from app.schemas import Credentials, Envelope, UserOut, TokenOut, KBInput, KBOut

router = APIRouter(prefix="/api")


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return salt + ":" + digest


@router.post("/auth/register", response_model=Envelope[UserOut], status_code=201)
def register(body: Credentials, db=Depends(get_db)):
    user = User(username=body.username, password_hash=password_hash(body.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError("CONFLICT", "用户名已存在", 409) from None
    return ok(user)


@router.post("/auth/login", response_model=Envelope[TokenOut])
def login(body: Credentials, request: Request, db=Depends(get_db)):
    user = db.scalar(select(User).where(User.username == body.username))
    # Constant-cost hashing for unknown usernames too.
    stored = user.password_hash if user else "0" * 32 + ":" + "0" * 128
    candidate = password_hash(body.password, stored.split(":")[0])
    if not hmac.compare_digest(stored, candidate) or not user:
        raise AppError("UNAUTHORIZED", "用户名或密码错误", 401)
    cfg = request.app.state.settings
    token = jwt.encode({"sub": user.id, "exp": datetime.now(timezone.utc) + timedelta(hours=cfg.token_hours)}, cfg.jwt_secret.get_secret_value(), algorithm="HS256")
    return ok({"access_token": token, "user": user})


@router.get("/auth/me", response_model=Envelope[UserOut])
def me(user=Depends(current_user)):
    return ok(user)


@router.get("/knowledge-bases", response_model=Envelope[list[KBOut]])
def list_kbs(db=Depends(get_db), user=Depends(current_user)):
    return ok(db.scalars(select(KnowledgeBase).where(KnowledgeBase.owner_id == user.id).order_by(KnowledgeBase.created_at.desc())).all())


@router.post("/knowledge-bases", response_model=Envelope[KBOut], status_code=201)
def create_kb(body: KBInput, db=Depends(get_db), user=Depends(current_user)):
    row = KnowledgeBase(owner_id=user.id, **body.model_dump())
    db.add(row)
    save_kb(db)
    return ok(row)


def save_kb(db):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError("CONFLICT", "知识库名称已存在", 409) from None


@router.get("/knowledge-bases/{kb_id}", response_model=Envelope[KBOut])
def get_kb(kb_id: str, db=Depends(get_db), user=Depends(current_user)):
    return ok(owned_kb(db, user, kb_id))


@router.put("/knowledge-bases/{kb_id}", response_model=Envelope[KBOut])
def update_kb(kb_id: str, body: KBInput, db=Depends(get_db), user=Depends(current_user)):
    row = owned_kb(db, user, kb_id)
    row.name, row.description = body.name, body.description
    save_kb(db)
    return ok(row)


@router.delete("/knowledge-bases/{kb_id}", response_model=Envelope[None])
def delete_kb(kb_id: str, request: Request, db=Depends(get_db), user=Depends(current_user)):
    from app.services.documents import delete_knowledge_base
    with request.app.state.lock:
        delete_knowledge_base(request.app.state, db, owned_kb(db, user, kb_id))
    return ok()
