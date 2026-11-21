"""M5-only request gate. Importing this module never loads settings or credentials."""
import argparse
from contextlib import asynccontextmanager
from decimal import Decimal
import hashlib
import importlib.util
import json
import re
from pathlib import Path
from threading import RLock
import sys

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
from real_rag_acceptance import load_key, need, Stop, QUESTION, digest
from m5_preflight import claim_artifact, check_initialized, check_owned, TABLES


class ModelBudget:
    def __init__(self, ledger_path, context):
        self.path, self.context, self.lock = ledger_path, context, RLock()
        self.state = {"status": "READY", "calls": [], "upload_posts": 0, "message_posts": 0}
        with self.path.open("x", encoding="utf-8") as target:
            target.write(json.dumps(self.state))

    def save(self):
        self.path.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")

    def halt(self, code):
        self.state.update(status="STOPPED", reason=code)
        self.save()

    def reserve_post(self, kind):
        with self.lock:
            need(self.state["status"] == "READY", "ACCEPTANCE_STOPPED")
            key = kind + "_posts"
            if self.state[key] != 0:
                self.halt("DUPLICATE_" + kind.upper())
                raise Stop("ACCEPTANCE_STOPPED")
            self.state[key] = 1
            self.save()

    def call(self, original, model, path, body, error_code):
        with self.lock:
            need(self.state["status"] == "READY", "ACCEPTANCE_STOPPED")
            index = len(self.state["calls"])
            try:
                need(index < 3 and path == ["/embeddings", "/embeddings", "/chat/completions"][index], "REQUEST_LIMIT_OR_ORDER")
                body = dict(body)
                if index < 2:
                    text = self.context if index == 0 else QUESTION
                    need(body.get("input") == [text] and body.get("model") == "text-embedding-v4" and body.get("dimensions") == 1024, "UNPLANNED_EMBEDDING")
                    need(len(text.encode()) <= [256, 128][index], "INPUT_LIMIT")
                else:
                    need(body.get("model") == "qwen-plus" and len(body.get("messages", [])) == 2, "UNPLANNED_GENERATION")
                    user = json.loads(body["messages"][-1]["content"])
                    need(user == {"question": QUESTION, "untrusted_evidence": [{"source_id": 1, "text": self.context}]}, "UNPLANNED_CONTEXT")
                    need(len(json.dumps(body["messages"], ensure_ascii=False).encode()) <= 2048, "INPUT_LIMIT")
                    body.update(max_tokens=256, enable_thinking=False, stream=False)
                need(Decimal("0.0039808") <= Decimal("0.01"), "BUDGET_LIMIT")
                entry = {"attempt": index + 1, "path": path, "status": "UNKNOWN_CHARGE"}
                self.state["calls"].append(entry)
                self.save()
                result = original(model, path, body, error_code)
                usage = result.get("usage", {})
                inputs = usage.get("prompt_tokens", usage.get("input_tokens", usage.get("total_tokens") if index < 2 else None))
                outputs = usage.get("completion_tokens", 0) if index == 2 else 0
                need(type(inputs) is int and 0 <= inputs <= [256, 128, 4096][index], "USAGE_NOT_VERIFIED")
                need(type(outputs) is int and 0 <= outputs <= 256, "OUTPUT_LIMIT")
                if index == 2:
                    need(result["choices"][0].get("finish_reason") == "stop", "INCOMPLETE_GENERATION")
                    need(not result["choices"][0]["message"].get("reasoning_content"), "UNEXPECTED_THINKING")
                cost = (Decimal(inputs) * Decimal("0.5" if index < 2 else "0.8") + Decimal(outputs) * 2) / 1000000
                entry.update(status="HTTP_OK", input_tokens=inputs, output_tokens=outputs, estimated_cny=str(cost))
                self.save()
                return result
            except Exception:
                self.halt("MODEL_OR_BUDGET_FAILURE")
                raise Stop("ACCEPTANCE_STOPPED") from None


def serve(args):
    sys.path.insert(0, "/app")
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    need(args.approve == plan["approval_id"], "EXPLICIT_M5_APPROVAL_REQUIRED")
    need(plan["status"] == "PENDING_APPROVAL", "PLAN_ALREADY_EXECUTED")
    for name, expected in plan["script_hashes"].items():
        need(digest((SCRIPTS / name).read_bytes()) == expected, "SCRIPT_CHANGED")
    need(digest(args.document.read_bytes()) == plan["document_sha256"], "DOCUMENT_CHANGED")
    need(re.fullmatch(r"[0-9a-f]{12}", plan["run_id"]), "INVALID_SCOPE")
    need(plan["schema"] == "rag_m5_" + plan["run_id"], "INVALID_SCOPE")
    need(plan["artifact_dir"] == "/data/m5-acceptance/" + plan["run_id"], "INVALID_SCOPE")
    need(plan["max_embedding_requests"] == 2 and plan["max_qwen_requests"] == 1 and plan["budget_cny"] == "0.01", "LIMIT_CHANGED")
    from app.core.config import Settings
    from app.core.db import make_database
    from app.core.errors import ok
    from app.main import create_app
    from app.rag.parsing import parse, split
    from app.rag.providers import QwenModels
    from app.rag.vectors import get_vectors
    from app.api.deps import current_user
    from fastapi import Depends
    from fastapi.responses import JSONResponse
    from sqlalchemy import select, text
    from sqlalchemy.schema import CreateSchema, DropSchema
    from sqlalchemy.engine import make_url
    from app.models import Document

    for name, expected in plan["reviewed_sources"].items():
        need(digest((Path("/app/app") / name).read_bytes()) == expected, "BUSINESS_SOURCE_CHANGED")
    base = Settings()
    url = make_url(base.database_url.get_secret_value())
    need(url.drivername == "postgresql+psycopg" and url.host == "postgres" and url.database == "rag_knowledge", "RUN_INSIDE_PROJECT_COMPOSE")
    need(base.qwen_base_url.rstrip("/") == "https://dashscope.aliyuncs.com/compatible-mode/v1", "ENDPOINT_CHANGED")
    need(base.qwen_model == "qwen-plus" and base.embedding_model == "text-embedding-v4", "MODEL_CHANGED")
    need(base.min_score == 0.2, "SEARCH_THRESHOLD_CHANGED")
    parts = split(parse(str(args.document), "txt"), base.chunk_size, base.chunk_overlap)
    need(len(parts) == 1 and digest(parts[0][0].encode()) == plan["chunk_sha256"], "CHUNK_CHANGED")
    from importlib.metadata import version
    need(version("milvus-lite") == plan.get("milvus_lite_version") == "3.2.2", "M5_STORAGE_TYPE_INVALID")
    artifact = claim_artifact(Path("/data/m5-acceptance"), plan)
    key = load_key(args.key_file, args.key_env_file)  # Execution-only; never used by offline preparation.
    budget = ModelBudget(artifact / "ledger.json", parts[0][0])
    engine, _ = make_database(base.database_url.get_secret_value())
    created = False
    try:
        with engine.begin() as db:
            db.execute(CreateSchema(plan["schema"]))
        created = True
        scoped = url.update_query_dict({"options": "-csearch_path=" + plan["schema"]})
        values = base.model_dump()
        values.update(database_url=scoped.render_as_string(hide_password=False), model_backend="qwen",
                      allow_paid_models=True, dashscope_api_key=key, storage_dir=artifact / "uploads",
                      vector_uri=str(artifact / "vectors.db"), vector_backend="milvus")
        app = create_app(Settings(_env_file=None, **values))
        lifespan = app.router.lifespan_context
        original = QwenModels.call

        @asynccontextmanager
        async def guarded_lifespan(app):
            def counted(model, path, body, code):
                return budget.call(original, model, path, body, code)
            QwenModels.call = counted
            try:
                async with lifespan(app):
                    try:
                        vectors = get_vectors(app.state)
                        with app.state.engine.connect() as db:
                            rows = {name: db.scalar(text("SELECT count(*) FROM " + name)) for name in TABLES}
                        check_initialized(artifact.parent, plan, budget.state, rows,
                                          int(vectors.client.get_collection_stats(collection_name=vectors.collection)["row_count"]))
                    except Exception as exc:
                        budget.halt("M5_INITIAL_STATE_CHECK_FAILED")
                        raise Stop(str(exc) if isinstance(exc, Stop) else "M5_INITIAL_STATE_CHECK_FAILED") from None
                    yield
            finally:
                QwenModels.call = original

        app.router.lifespan_context = guarded_lifespan

        @app.middleware("http")
        async def protect_calls(request, call_next):
            path = request.url.path
            try:
                if request.method == "POST":
                    if path.endswith("/search"):
                        budget.halt("EXTRA_SEARCH_FORBIDDEN")
                        raise Stop("ACCEPTANCE_STOPPED")
                    if path.endswith("/documents"):
                        budget.reserve_post("upload")
                    if path.endswith("/messages"):
                        budget.reserve_post("message")
                response = await call_next(request)
                if request.method == "POST" and response.status_code >= 400:
                    budget.halt("API_MUTATION_FAILED")
                if request.method == "GET" and "/documents" in path:
                    with app.state.sessions() as db:
                        failed = db.scalar(select(Document.id).where(Document.status == "failed").limit(1))
                    if failed:
                        budget.halt("DOCUMENT_PROCESSING_FAILED")
                return response
            except Exception:
                budget.halt("API_OR_GUARD_FAILURE")
                return JSONResponse(status_code=409, content={"code":"ACCEPTANCE_STOPPED","message":"本次验收已停止，请勿重试","data":None,"request_id":"m5"})

        @app.get("/api/m5-control/status")
        def status(user=Depends(current_user)):
            return ok(budget.state)

        @app.post("/api/m5-control/stop")
        def stop(user=Depends(current_user)):
            budget.halt("BROWSER_STOPPED")
            return ok()

        @app.post("/api/m5-control/finish")
        def finish(user=Depends(current_user)):
            need(len(budget.state["calls"]) == 3 and all(c["status"] == "HTTP_OK" for c in budget.state["calls"]), "INCOMPLETE_RUN")
            need(budget.state["status"] == "READY", "ACCEPTANCE_STOPPED")
            budget.state["status"] = "PASS"
            budget.save()
            return ok()

        import uvicorn
        uvicorn.run(app, host="0.0.0.0", port=8000, workers=1, access_log=False, log_level="warning")
    finally:
        try:
            if created and budget.state["status"] == "PASS":
                check_owned(artifact.parent, plan)
                with engine.begin() as db:
                    db.execute(DropSchema(plan["schema"], cascade=True))
                budget.state["schema_cleanup"] = "PASS"
                budget.save()
        except Exception:
            budget.halt("CLEANUP_FAILED")
            raise Stop("CLEANUP_FAILED") from None
        finally:
            engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--approve", default="")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--document", type=Path)
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--key-env-file", type=Path)
    args = parser.parse_args()
    if not args.serve:
        print("OFFLINE_ONLY: explicit --serve and a new approved M5 plan are required")
        return 0
    try:
        need(args.plan is not None and args.document is not None, "PLAN_AND_DOCUMENT_REQUIRED")
        serve(args)
        return 0
    except Exception as exc:
        print("BLOCKED", str(exc) if isinstance(exc, Stop) else type(exc).__name__)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
