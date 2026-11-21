from pathlib import Path
from uuid import uuid4
from fastapi import APIRouter, BackgroundTasks, Depends, File, Request, UploadFile
from sqlalchemy import select
from app.api.deps import current_user, get_db, owned_kb, owned_document
from app.core.errors import AppError, ok
from app.models import Document
from app.schemas import DocumentOut, Envelope, SearchInput, Citation
from app.services.documents import process_document, delete_document

router = APIRouter(prefix="/api/knowledge-bases/{kb_id}")


@router.post("/documents", response_model=Envelope[DocumentOut], status_code=202)
def upload(kb_id: str, request: Request, tasks: BackgroundTasks, file: UploadFile = File(...), db=Depends(get_db), user=Depends(current_user)):
    owned_kb(db, user, kb_id)
    name = Path((file.filename or "").replace("\\", "/")).name
    kind = Path(name).suffix.lower().lstrip(".")
    if kind not in {"pdf", "docx", "txt", "md"}:
        raise AppError("UNSUPPORTED_FILE", "仅支持 PDF、DOCX、TXT、Markdown", 415)
    if not name or len(name) > 255:
        raise AppError("VALIDATION_ERROR", "文件名称不合法", 422)
    doc_id = str(uuid4())
    destination = request.app.state.settings.storage_dir / (doc_id + "." + kind)
    size = 0
    try:
        with destination.open("wb") as target:
            while block := file.file.read(64 * 1024):
                size += len(block)
                if size > request.app.state.settings.max_upload_bytes:
                    raise AppError("FILE_TOO_LARGE", "文件超过允许大小", 413)
                target.write(block)
        if size == 0:
            raise AppError("VALIDATION_ERROR", "文件不能为空", 422)
        row = Document(id=doc_id, knowledge_base_id=kb_id, name=name, file_type=kind, file_path=str(destination), size=size)
        db.add(row)
        db.commit()
    except Exception:
        destination.unlink(missing_ok=True)
        db.rollback()
        raise
    finally:
        file.file.close()
    tasks.add_task(process_document, request.app.state, doc_id)
    return ok(row)


@router.get("/documents", response_model=Envelope[list[DocumentOut]])
def list_documents(kb_id: str, db=Depends(get_db), user=Depends(current_user)):
    owned_kb(db, user, kb_id)
    return ok(db.scalars(select(Document).where(Document.knowledge_base_id == kb_id).order_by(Document.created_at.desc())).all())


@router.get("/documents/{doc_id}", response_model=Envelope[DocumentOut])
def status(kb_id: str, doc_id: str, db=Depends(get_db), user=Depends(current_user)):
    return ok(owned_document(db, user, kb_id, doc_id))


@router.delete("/documents/{doc_id}", response_model=Envelope[None])
def remove(kb_id: str, doc_id: str, request: Request, db=Depends(get_db), user=Depends(current_user)):
    with request.app.state.lock:
        delete_document(request.app.state, db, owned_document(db, user, kb_id, doc_id))
    return ok()


@router.post("/search", response_model=Envelope[list[Citation]])
def search(kb_id: str, body: SearchInput, request: Request, db=Depends(get_db), user=Depends(current_user)):
    from app.services.chat import retrieve
    owned_kb(db, user, kb_id)
    with request.app.state.lock:
        return ok(retrieve(request.app.state, db, kb_id, body.question, body.top_k))
