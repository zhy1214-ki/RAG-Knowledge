from contextlib import asynccontextmanager
import hashlib
import json
from fastapi import APIRouter, BackgroundTasks, Depends, File, Request, UploadFile
from app.api import base, chat, documents
from app.api.deps import current_user, get_db, owned_kb, owned_session
from app.core.errors import AppError
from app.factory import create_app
from app.models import Document
from app.schemas import Citation, DocumentOut, Envelope, MessageInput, MessageOut, SearchInput
from app.real_usage.guard import UsageGuard
from app.real_usage.models import GuardedModels
from app.rag.providers import DisabledModels
from app.rag.vectors import get_vectors

router = APIRouter()


@router.post("/api/knowledge-bases/{kb_id}/documents", response_model=Envelope[DocumentOut], status_code=202)
def upload(kb_id: str, request: Request, tasks: BackgroundTasks, file: UploadFile = File(...),
           db=Depends(get_db), user=Depends(current_user)):
    owned_kb(db, user, kb_id)
    digest, size = hashlib.sha256(), 0
    while block := file.file.read(64 * 1024):
        size += len(block)
        if size > request.app.state.settings.max_upload_bytes:
            raise AppError("FILE_TOO_LARGE", "文件超过本环境允许大小", 413)
        digest.update(block)
    file.file.seek(0)
    guard = request.app.state.usage_guard
    operation = guard.begin_operation(user.id, kb_id, "upload", digest.hexdigest())
    staged = BackgroundTasks()
    try:
        response = documents.upload(kb_id, request, staged, file, db, user)
    except Exception:
        guard.finish_operation(operation, False)
        raise
    document_id = response["data"].id

    async def index_and_finish():
        success = False
        try:
            await staged()
            with request.app.state.sessions() as check:
                row = check.get(Document, document_id)
                success = row is not None and row.status == "indexed"
        finally:
            guard.finish_operation(operation, success)
    tasks.add_task(index_and_finish)
    return response


def fingerprint(body):
    return hashlib.sha256(json.dumps(body.model_dump(), sort_keys=True).encode()).hexdigest()


@router.post("/api/knowledge-bases/{kb_id}/search", response_model=Envelope[list[Citation]])
def search(kb_id: str, body: SearchInput, request: Request, db=Depends(get_db), user=Depends(current_user)):
    owned_kb(db, user, kb_id)
    guard = request.app.state.usage_guard
    operation = guard.begin_operation(user.id, kb_id, "search", fingerprint(body))
    success = False
    try:
        result = documents.search(kb_id, body, request, db, user)
        success = True
        return result
    finally:
        guard.finish_operation(operation, success)


@router.post("/api/sessions/{session_id}/messages", response_model=Envelope[MessageOut])
def send(session_id: str, body: MessageInput, request: Request, db=Depends(get_db), user=Depends(current_user)):
    owned_session(db, user, session_id)
    guard = request.app.state.usage_guard
    operation = guard.begin_operation(user.id, session_id, "message", fingerprint(body))
    success = False
    try:
        result = chat.send(session_id, body, request, db, user)
        success = True
        return result
    finally:
        guard.finish_operation(operation, success)


def create_real_app(settings, models_factory=None):
    if settings.rag_runtime_mode not in {"infrastructure", "real"}:
        raise AppError("MODEL_DISABLED", "Invalid model runtime mode", 403)
    def setup(state):
        state.usage_guard = UsageGuard(state.engine, state.sessions, settings)
        if settings.rag_runtime_mode == "infrastructure":
            state.models = DisabledModels()
            get_vectors(state)
        else:
            state.models = (models_factory or GuardedModels)(settings, state.usage_guard)
    guarded = {("/api/knowledge-bases/{kb_id}/documents", "POST"),
               ("/api/knowledge-bases/{kb_id}/search", "POST"),
               ("/api/sessions/{session_id}/messages", "POST")}
    readers = []
    for original in (documents.router, chat.router):
        reader = APIRouter()
        reader.routes.extend(route for route in original.routes if not any(
            (route.path, method) in guarded for method in route.methods))
        readers.append(reader)
    app = create_app(settings, setup=setup, api_routers=(base.router, *readers, router))
    original_lifespan = app.router.lifespan_context
    @asynccontextmanager
    async def safe_lifespan(application):
        try:
            async with original_lifespan(application):
                yield
        except Exception:
            raise RuntimeError("R1_RUNTIME_INITIALIZATION_OR_SHUTDOWN_FAILED") from None
    app.router.lifespan_context = safe_lifespan
    return app
