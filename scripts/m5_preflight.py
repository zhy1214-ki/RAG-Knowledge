"""M5-only filesystem/state preflight. No settings, credentials, Docker or model calls."""
import json
import re
from pathlib import Path
from real_rag_acceptance import need, Stop

TABLES = ("users", "knowledge_bases", "documents", "document_chunks", "chat_sessions", "chat_messages")
COLLECTION = "rag_qwen_1024_v1"


def checked_path(path, parent):
    path, parent = Path(path), Path(parent)
    need(path.is_absolute() and parent.is_absolute() and ".." not in path.parts,
         "M5_PATH_OUTSIDE_SCOPE")
    need(path == parent or parent in path.parents, "M5_PATH_OUTSIDE_SCOPE")
    for part in (path, *path.parents):
        need(not part.is_symlink() and not part.is_junction(), "M5_PATH_LINK_FORBIDDEN")
    need(path.resolve() == path, "M5_PATH_OUTSIDE_SCOPE")
    return path


def artifact_path(parent, plan):
    need(re.fullmatch(r"[0-9a-f]{12}", plan["run_id"]) is not None, "INVALID_SCOPE")
    need(plan["schema"] == "rag_m5_" + plan["run_id"], "INVALID_SCOPE")
    need(plan["artifact_dir"] == "/data/m5-acceptance/" + plan["run_id"], "INVALID_SCOPE")
    return checked_path(Path(parent) / plan["run_id"], parent)


def owner_record(plan):
    return {"approval_id": plan["approval_id"], "run_id": plan["run_id"]}


def claim_artifact(parent, plan):
    """Before native initialization: even an unowned empty run directory conflicts."""
    need(plan.get("vector_storage_type") == "directory" and plan.get("milvus_lite_version") == "3.2.2",
         "M5_STORAGE_TYPE_INVALID")
    artifact = artifact_path(parent, plan)
    try:
        Path(parent).mkdir(parents=True, exist_ok=True)
        artifact.mkdir()  # Atomic claim; never reuse/remove a prior run.
    except FileExistsError:
        raise Stop("M5_RESOURCE_ALREADY_EXISTS") from None
    except OSError:
        raise Stop("M5_INITIAL_STATE_CHECK_FAILED") from None
    with (artifact / "preflight-owner.json").open("x", encoding="utf-8") as target:
        json.dump(owner_record(plan), target)
    return artifact


def check_owned(parent, plan):
    artifact = artifact_path(parent, plan)
    marker = checked_path(artifact / "preflight-owner.json", artifact)
    need(artifact.is_dir() and marker.is_file(), "M5_RESOURCE_OWNERSHIP_ERROR")
    try:
        owner = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise Stop("M5_RESOURCE_OWNERSHIP_ERROR") from None
    need(owner == owner_record(plan), "M5_RESOURCE_OWNERSHIP_ERROR")
    return artifact


def check_vector_directory(vector, storage_type):
    # Pinned milvus-lite 3.2.2 server_manager.py uses the .db URI as data_dir.
    checked_path(vector, vector.parent)
    need(storage_type == "directory", "M5_STORAGE_TYPE_INVALID")
    need(vector.exists(), "M5_STORAGE_PATH_MISSING")
    need(vector.is_dir(), "M5_STORAGE_TYPE_INVALID")
    collection = "collections/" + COLLECTION
    # Native empty-store layout from db.py, schema/persistence.py, manifest.py,
    # and lazy WAL initialization. WAL/data/segment files imply prior writes.
    directories = {"collections", "databases", ".database-staging", collection, collection + "/wal"}
    files = {"LOCK", collection + "/schema.json", collection + "/manifest.json",
             collection + "/manifest.json.prev"}
    pending = [vector]
    while pending:
        for item in pending.pop().iterdir():
            checked_path(item, vector)  # Reject links before traversing.
            relative = item.relative_to(vector).as_posix()
            need(relative in directories or relative in files, "M5_RESOURCE_ALREADY_EXISTS")
            if relative in directories:
                need(item.is_dir(), "M5_STORAGE_TYPE_INVALID")
                pending.append(item)
            else:
                need(item.is_file(), "M5_STORAGE_TYPE_INVALID")


def check_initialized(parent, plan, budget_state, table_rows, vector_rows):
    """Read-only post-init check; run before accepting any browser/API writes."""
    artifact = check_owned(parent, plan)
    need(plan.get("milvus_lite_version") == "3.2.2", "M5_STORAGE_TYPE_INVALID")
    need(budget_state == {"status": "READY", "calls": [], "upload_posts": 0, "message_posts": 0},
         "M5_INITIAL_STATE_CHECK_FAILED")
    need(set(table_rows) == set(TABLES) and all(type(n) is int and n == 0 for n in table_rows.values()),
         "M5_INITIAL_STATE_CHECK_FAILED")
    need(type(vector_rows) is int and vector_rows == 0, "M5_INITIAL_STATE_CHECK_FAILED")
    allowed = {"preflight-owner.json", "ledger.json", "uploads", "vectors.db"}
    for item in artifact.iterdir():
        checked_path(item, artifact)
        need(item.name in allowed, "M5_RESOURCE_ALREADY_EXISTS")
    ledger = checked_path(artifact / "ledger.json", artifact)
    uploads = checked_path(artifact / "uploads", artifact)
    vector = checked_path(artifact / "vectors.db", artifact)
    need(ledger.is_file() and uploads.is_dir(), "M5_INITIAL_STATE_CHECK_FAILED")
    try:
        on_disk = json.loads(ledger.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise Stop("M5_INITIAL_STATE_CHECK_FAILED") from None
    need(on_disk == budget_state, "M5_INITIAL_STATE_CHECK_FAILED")
    need(not any(uploads.iterdir()), "M5_RESOURCE_ALREADY_EXISTS")
    check_vector_directory(vector, plan.get("vector_storage_type"))
    return {"status": "PASS", "vector_storage_type": "directory", "table_rows": table_rows,
            "vector_rows": 0, "model_requests": 0}
