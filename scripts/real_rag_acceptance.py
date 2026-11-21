"""Offline preparation by default. Execution requires a separate explicit approval."""
import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" if (ROOT / "backend").exists() else Path.cwd()))
QUESTION = "What is the return period in the RAG acceptance policy? Give the number of days and cite the source."
SOURCE_FILES = ["core/config.py", "rag/providers.py", "rag/vectors.py", "services/documents.py", "services/chat.py"]


class Stop(Exception):
    pass


def need(condition, code):
    if not condition:
        raise Stop(code)


def load_key(key_file=None, key_env_file=None):
    """Nonempty process environment > explicit dotenv file > legacy raw file."""
    key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if key:
        need("\n" not in key and "\r" not in key, "KEY_ENVIRONMENT_INVALID")
        return key
    if key_env_file is not None:
        need(key_env_file.is_file(), "KEY_ENV_FILE_NOT_FOUND")
        try:
            values = dotenv_values(key_env_file, encoding="utf-8-sig", interpolate=False)
        except Exception:
            raise Stop("KEY_ENV_FILE_READ_ERROR") from None
        need("DASHSCOPE_API_KEY" in values, "KEY_ENV_VARIABLE_MISSING")
        key = (values["DASHSCOPE_API_KEY"] or "").strip()
        need(bool(key), "KEY_ENV_VALUE_EMPTY")
    elif key_file is not None:
        need(key_file.is_file(), "KEY_FILE_NOT_FOUND")
        try:
            key = key_file.read_text(encoding="utf-8-sig").strip()
        except Exception:
            raise Stop("KEY_FILE_READ_ERROR") from None
    else:
        raise Stop("KEY_REQUIRED")
    need(bool(key) and "\n" not in key and "\r" not in key, "KEY_FILE_EMPTY_OR_INVALID")
    return key


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def reviewed_sources():
    import app
    base = Path(app.__file__).parent
    return {name: digest((base / name).read_bytes()) for name in SOURCE_FILES}


def prepare(plan_path, document):
    from app.core.config import Settings
    from app.rag.parsing import parse, split
    cfg = Settings(_env_file=ROOT / ".env", model_backend="mock", allow_paid_models=False)
    parts = split(parse(str(document), "txt"), cfg.chunk_size, cfg.chunk_overlap)
    need(len(parts) == 1 and len(parts[0][0].encode()) <= 256, "DOCUMENT_MUST_BE_ONE_SMALL_CHUNK")
    need(len(QUESTION.encode()) <= 128, "QUESTION_TOO_LARGE")
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    if plan_path.exists():
        old = json.loads(plan_path.read_text(encoding="utf-8"))
        need(old["document_sha256"] == digest(document.read_bytes()), "DOCUMENT_CHANGED")
        need(old["reviewed_sources"] == reviewed_sources(), "REVIEWED_SOURCE_CHANGED")
        need(old.get("runner_sha256") == digest(Path(__file__).read_bytes()), "REVIEWED_RUNNER_CHANGED")
        print("PREPARED_EXISTING_PLAN", old["run_id"], "paid_requests=0")
        return
    run_id = uuid4().hex[:12]
    write_json(plan_path, {
        "run_id": run_id, "approval_id": run_id, "status": "BLOCKED", "reason": "AWAITING_EXPLICIT_APPROVAL_AND_KEY",
        "document_name": document.name, "document_sha256": digest(document.read_bytes()),
        "chunk_sha256": digest(parts[0][0].encode()), "chunk_count": 1, "question": QUESTION,
        "endpoint": cfg.qwen_base_url.rstrip("/"), "qwen_model": "qwen-plus",
        "embedding_model": "text-embedding-v4", "dimension": 1024,
        "request_order": ["/embeddings", "/embeddings", "/chat/completions"],
        "max_requests": 3, "retries": 0, "qwen_max_tokens": 256, "enable_thinking": False,
        "reserved_input_tokens": [256, 128, 4096], "budget_cny": "0.01",
        "reserved_cost_cny": "0.0039808", "pricing_region": "Beijing",
        "rates_cny_per_million": {"embedding": "0.5", "qwen_input": "0.8", "qwen_output": "2"},
        "schema": "rag_real_" + run_id, "artifact_dir": "/data/real-acceptance/" + run_id,
        "reviewed_sources": reviewed_sources(), "runner_sha256": digest(Path(__file__).read_bytes()), "paid_requests_sent": 0,
        "real_embedding": "NOT_VERIFIED", "real_qwen": "NOT_VERIFIED", "real_rag": "NOT_VERIFIED"
    })
    print("PREPARED", run_id, "chunks=1 paid_requests=0 reserved_cny=0.0039808 budget_cny=0.01")


def execute(args, plan):
    # No database, vector or provider activity is allowed before these gates.
    need(args.approve == plan.get("approval_id", plan["run_id"]), "EXPLICIT_APPROVAL_ARGUMENT_REQUIRED")
    need(plan.get("runner_sha256") == digest(Path(__file__).read_bytes()), "REVIEWED_RUNNER_CHANGED")
    key = load_key(args.key_file, args.key_env_file)
    need(args.document.name == plan["document_name"] and digest(args.document.read_bytes()) == plan["document_sha256"], "DOCUMENT_CHANGED")
    need(plan["reviewed_sources"] == reviewed_sources(), "REVIEWED_SOURCE_CHANGED")
    need(re.fullmatch(r"[0-9a-f]{12}", plan["run_id"]), "INVALID_RUN_ID")
    need(plan["schema"] == "rag_real_" + plan["run_id"], "INVALID_SCHEMA")
    need(plan["artifact_dir"] == "/data/real-acceptance/" + plan["run_id"], "INVALID_ARTIFACT_SCOPE")
    need(plan["request_order"] == ["/embeddings", "/embeddings", "/chat/completions"], "INVALID_REQUEST_PLAN")
    need(plan["budget_cny"] == "0.01" and plan["qwen_max_tokens"] == 256, "BUDGET_PLAN_CHANGED")

    from fastapi.testclient import TestClient
    from sqlalchemy.engine import make_url
    from sqlalchemy.schema import CreateSchema, DropSchema
    from sqlalchemy import select, func
    from app.core.config import Settings
    from app.core.db import make_database
    from app.core.errors import AppError
    from app.main import create_app
    from app.models import DocumentChunk
    from app.rag.parsing import parse, split
    from app.rag.providers import QwenModels
    from app.rag.vectors import get_vectors

    base = Settings()
    url = make_url(base.database_url.get_secret_value())
    need(url.drivername == "postgresql+psycopg" and url.database == "rag_knowledge" and url.host == "postgres", "RUN_INSIDE_PROJECT_COMPOSE_BACKEND")
    need(base.qwen_base_url.rstrip("/") == plan["endpoint"] == "https://dashscope.aliyuncs.com/compatible-mode/v1", "UNREVIEWED_REGION_OR_ENDPOINT")
    need(base.qwen_model == plan["qwen_model"] == "qwen-plus" and base.embedding_model == plan["embedding_model"] == "text-embedding-v4", "MODEL_CHANGED")
    parts = split(parse(str(args.document), "txt"), base.chunk_size, base.chunk_overlap)
    need(len(parts) == 1 and digest(parts[0][0].encode()) == plan["chunk_sha256"], "CHUNK_PLAN_CHANGED")
    artifact_dir = Path(plan["artifact_dir"])
    artifact_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = artifact_dir / "ledger.json"
    with ledger_path.open("x", encoding="utf-8") as f:
        f.write("{}")  # A previous run, including a timeout, cannot be silently repeated.
    state = {"run_id": plan["run_id"], "status": "NOT_VERIFIED", "calls": [],
             "embedding_document": "NOT_VERIFIED", "embedding_query": "NOT_VERIFIED",
             "qwen": "NOT_VERIFIED", "rag": "NOT_VERIFIED", "cleanup": "NOT_VERIFIED"}
    original_call = QwenModels.call
    query_vector = None

    def save():
        write_json(ledger_path, state)

    def counted_call(model, path, body, code):
        nonlocal query_vector
        index = len(state["calls"])
        need(state["status"] != "FAIL" and index < 3 and path == plan["request_order"][index], "REQUEST_BUDGET_OR_ORDER_VIOLATION")
        body = dict(body)
        if index < 2:
            expected = parts[0][0] if index == 0 else QUESTION
            need(body.get("input") == [expected] and body.get("dimensions") == 1024, "UNPLANNED_EMBEDDING_INPUT")
            need(body.get("model") == "text-embedding-v4", "UNPLANNED_MODEL")
        else:
            need(body.get("model") == "qwen-plus" and len(body["messages"]) == 2, "UNPLANNED_MODEL_OR_HISTORY")
            evidence = json.loads(body["messages"][-1]["content"])
            need(evidence == {"question": QUESTION, "untrusted_evidence": [{"source_id": 1, "text": parts[0][0]}]}, "UNPLANNED_CONTEXT")
            need(len(json.dumps(body["messages"], ensure_ascii=False).encode()) <= 2048, "PROMPT_TOO_LARGE")
            body.update(max_tokens=256, enable_thinking=False, stream=False)
        reserved = Decimal("0.0039808")
        need(reserved <= Decimal(plan["budget_cny"]), "BUDGET_EXCEEDED")
        entry = {"attempt": index + 1, "path": path, "model": body["model"],
                 "status": "NOT_VERIFIED", "sent_at": datetime.now(timezone.utc).isoformat(),
                 "payload_sha256": digest(json.dumps(body, sort_keys=True).encode())}
        state["calls"].append(entry)
        save()  # Count before dispatch; timeout is an unknown-charge attempt, never a retry.
        try:
            payload = original_call(model, path, body, code)
            usage = payload.get("usage", {})
            prompt = usage.get("prompt_tokens", usage.get("input_tokens", usage.get("total_tokens") if index < 2 else None))
            completion = usage.get("completion_tokens", 0) if index == 2 else 0
            need(type(prompt) is int and prompt >= 0 and type(completion) is int and completion >= 0, "USAGE_NOT_VERIFIED")
            need(prompt <= plan["reserved_input_tokens"][index] and completion <= 256, "TOKEN_RESERVATION_EXCEEDED")
            if index == 2:
                need(payload["choices"][0].get("finish_reason") == "stop", "INCOMPLETE_GENERATION")
                need(not payload["choices"][0]["message"].get("reasoning_content"), "UNEXPECTED_THINKING_OUTPUT")
            if index == 1:
                query_vector = payload["data"][0]["embedding"]
            rate = Decimal("0.5") if index < 2 else Decimal("0.8")
            cost = (Decimal(prompt) * rate + Decimal(completion) * 2) / 1_000_000
            entry.update(status="HTTP_OK", prompt_tokens=prompt, completion_tokens=completion, usage_cost_estimate_cny=str(cost))
            save()
            return payload
        except Exception as exc:
            entry["status"] = "FAIL_OR_UNKNOWN_CHARGE"
            state.update(status="FAIL", stop_reason=exc.code if isinstance(exc, AppError) else str(exc) if isinstance(exc, Stop) else type(exc).__name__)
            save()
            raise

    admin_engine = None
    try:
        admin_engine, _ = make_database(url.render_as_string(hide_password=False))
        with admin_engine.begin() as connection:
            connection.execute(CreateSchema(plan["schema"]))  # No IF NOT EXISTS / no public writes.
        scoped = url.update_query_dict({"options": "-csearch_path=" + plan["schema"]})
        values = base.model_dump()
        values.update(database_url=scoped.render_as_string(hide_password=False), model_backend="qwen",
                      allow_paid_models=True, dashscope_api_key=key, vector_backend="milvus",
                      storage_dir=artifact_dir / "uploads", vector_uri=str(artifact_dir / "vectors.db"))
        cfg = Settings(_env_file=None, **values)
        app = create_app(cfg)
        with patch.object(QwenModels, "call", counted_call), TestClient(app, raise_server_exceptions=False) as client:
            get_vectors(app.state)  # Fail local storage initialization before any paid call.
            def api(method, path, **kwargs):
                response = client.request(method, "/api" + path, **kwargs)
                need(response.status_code < 300, "LOCAL_API_" + response.json().get("code", "ERROR"))
                return response.json()["data"]
            password = uuid4().hex
            username = "real_" + plan["run_id"]
            api("POST", "/auth/register", json={"username": username, "password": password})
            token = api("POST", "/auth/login", json={"username": username, "password": password})["access_token"]
            client.headers["Authorization"] = "Bearer " + token
            kb = api("POST", "/knowledge-bases", json={"name": username})["id"]
            with args.document.open("rb") as f:
                doc = api("POST", f"/knowledge-bases/{kb}/documents", files={"file": (args.document.name, f)})["id"]
            row = api("GET", f"/knowledge-bases/{kb}/documents/{doc}")
            need(row["status"] == "indexed" and row["chunk_count"] == 1 and len(state["calls"]) == 1, "INDEX_NOT_VERIFIED")
            state["embedding_document"] = "PASS"
            session = api("POST", "/sessions", json={"knowledge_base_id": kb})["id"]
            answer = api("POST", f"/sessions/{session}/messages", json={"question": QUESTION, "top_k": 1})
            need(len(state["calls"]) == 3 and ("17" in answer["content"] or "十七" in answer["content"]), "ANSWER_NOT_VERIFIED")
            need(len(answer["citations"]) == 1, "CITATIONS_NOT_VERIFIED")
            source = answer["citations"][0]
            need(source["document_id"] == doc and source["source_name"] == args.document.name and source["text"] == parts[0][0], "SOURCE_NOT_VERIFIED")
            need(source["source_id"] == 1 and "page" not in source["source_location"], "SOURCE_LOCATION_NOT_VERIFIED")
            messages = api("GET", f"/sessions/{session}/messages")
            need(len(messages) == 2 and messages[-1]["citations"] == answer["citations"], "HISTORY_NOT_VERIFIED")
            state.update(embedding_query="PASS", qwen="PASS", rag="PASS",
                         evidence={"knowledge_base_id": kb, "document_id": doc, "session_id": session,
                                   "answer": answer["content"], "citation_chunk_id": source["chunk_id"], "score": source["score"]})
            api("DELETE", f"/knowledge-bases/{kb}/documents/{doc}")
            need(query_vector is not None and not get_vectors(app.state).search(kb, query_vector, 1), "VECTOR_DELETE_NOT_VERIFIED")
            with app.state.sessions() as db:
                need(db.scalar(select(func.count()).select_from(DocumentChunk)) == 0, "CHUNK_DELETE_NOT_VERIFIED")
            api("DELETE", f"/knowledge-bases/{kb}")
        with admin_engine.begin() as connection:
            connection.execute(DropSchema(plan["schema"], cascade=True))
        state.update(status="PASS", cleanup="PASS")
    except Exception as exc:
        state.update(status="FAIL", stop_reason=exc.code if isinstance(exc, AppError) else str(exc) if isinstance(exc, Stop) else type(exc).__name__)
        # Preserve only this isolated test scope for diagnosis. Never resume paid work.
    finally:
        if admin_engine is not None:
            admin_engine.dispose()
        save()
    print(json.dumps({"status": state["status"], "requests_attempted": len(state["calls"]),
                      "cleanup": state["cleanup"], "ledger": str(ledger_path)}))
    return 0 if state["status"] == "PASS" else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--plan", type=Path, default=ROOT / "data/real-acceptance/plan.json")
    parser.add_argument("--document", type=Path, default=ROOT / "samples/real-rag-policy.txt")
    parser.add_argument("--approve", default="")
    parser.add_argument("--key-file", type=Path, help="Legacy raw key file (lowest priority)")
    parser.add_argument("--key-env-file", type=Path, help="Dotenv file containing DASHSCOPE_API_KEY")
    args = parser.parse_args()
    try:
        if not args.execute:
            prepare(args.plan, args.document)
            return 0
        return execute(args, json.loads(args.plan.read_text(encoding="utf-8")))
    except Exception as exc:
        # No raw exceptions, credentials, provider payloads or tracebacks.
        print("BLOCKED", str(exc) if isinstance(exc, Stop) else type(exc).__name__)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
