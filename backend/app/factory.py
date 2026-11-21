from contextlib import asynccontextmanager
from pathlib import Path
from threading import RLock
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import Settings
from app.core.db import make_database
from app.core.errors import install_handlers, ok
from app.models import Base, Document
from sqlalchemy import select
from app.schemas import ErrorResponse
from app.api.documents import router as documents_router
from app.api.chat import router as chat_router
from app.api.base import router


def create_app(settings=None, setup=None, api_routers=None):
    cfg = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        cfg.storage_dir.mkdir(parents=True, exist_ok=True)
        if cfg.database_url.get_secret_value().startswith("sqlite:///"):
            Path(cfg.database_url.get_secret_value().removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        engine, sessions = make_database(cfg.database_url.get_secret_value())
        Base.metadata.create_all(engine)
        app.state.engine, app.state.sessions = engine, sessions
        app.state.settings, app.state.lock = cfg, RLock()
        with sessions() as db:
            for doc in db.scalars(select(Document).where(Document.status.in_(["uploaded", "processing"]))).all():
                doc.status, doc.error_code, doc.progress = "failed", "PROCESS_INTERRUPTED", 0
            db.commit()
        if setup is not None:
            setup(app.state)
        yield
        if getattr(app.state, "vectors", None):
            app.state.vectors.close()
        engine.dispose()

    app = FastAPI(title="RAG Knowledge API", version="1.0.0", lifespan=lifespan,
                  responses={400: {"model": ErrorResponse}})
    app.add_middleware(CORSMiddleware, allow_origins=cfg.cors_origins, allow_credentials=False,
                       allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Authorization", "Content-Type"])
    safe_error = install_handlers(app)

    @app.middleware("http")
    async def safe_unhandled_errors(request, call_next):
        # Catch before ServerErrorMiddleware re-raises into the ASGI server logger.
        try:
            return await call_next(request)
        except Exception as exc:
            return await safe_error(request, exc)

    for api_router in api_routers if api_routers is not None else (router, documents_router, chat_router):
        app.include_router(api_router)

    @app.get("/api/health")
    def health():
        data = {"status": "ok", "model_backend": cfg.model_backend, "vector_backend": cfg.vector_backend}
        if hasattr(cfg, "rag_runtime_mode"):
            data["rag_runtime_mode"] = cfg.rag_runtime_mode
            data["paid_models_enabled"] = cfg.rag_runtime_mode == "real" and cfg.allow_paid_models
        return ok(data)
    return app


