"""Only the changed M5 preflight: fictional filesystem/state, no app/settings/Key/Docker."""
import hashlib
import importlib.util
import json
from pathlib import Path
import socket

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("m5_storage_guard_test", ROOT / "scripts/m5_browser_backend.py")
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)
import m5_preflight as preflight

EMPTY = {"status": "READY", "calls": [], "upload_posts": 0, "message_posts": 0}
ROWS = dict.fromkeys(preflight.TABLES, 0)


@pytest.fixture(autouse=True)
def no_external_actions(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("External action or credential load in offline preflight test")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(backend, "load_key", forbidden)


@pytest.fixture
def scope(tmp_path):
    parent = tmp_path / "m5-acceptance"
    parent.mkdir()
    plan = {"run_id": "abcdef123456", "approval_id": "fictional-m5-storage-v3",
            "schema": "rag_m5_abcdef123456", "artifact_dir": "/data/m5-acceptance/abcdef123456",
            "vector_storage_type": "directory", "milvus_lite_version": "3.2.2"}
    return parent, plan


def initialized(scope, native_files=False):
    parent, plan = scope
    artifact = preflight.claim_artifact(parent, plan)
    budget = backend.ModelBudget(artifact / "ledger.json", "fictional context")
    (artifact / "uploads").mkdir()
    vector = artifact / "vectors.db"
    vector.mkdir()
    if native_files:
        for relative in ("databases", ".database-staging", "collections/" + preflight.COLLECTION + "/wal"):
            (vector / relative).mkdir(parents=True)
        for relative in ("LOCK", "collections/" + preflight.COLLECTION + "/schema.json",
                         "collections/" + preflight.COLLECTION + "/manifest.json"):
            (vector / relative).write_text("{}")
    return artifact, budget


def check(scope, budget, rows=None, vector_rows=0):
    return preflight.check_initialized(*scope, budget.state, ROWS if rows is None else rows, vector_rows)


@pytest.mark.parametrize("native_files", [False, True])
def test_directory_store_accepts_empty_or_native_initialization_and_recheck(scope, native_files):
    artifact, budget = initialized(scope, native_files)
    before = {p.relative_to(artifact): p.read_bytes() for p in artifact.rglob("*") if p.is_file()}
    assert check(scope, budget)["status"] == "PASS"
    assert check(scope, budget)["status"] == "PASS"  # Read-only recheck must not claim again.
    assert before == {p.relative_to(artifact): p.read_bytes() for p in artifact.rglob("*") if p.is_file()}


def test_missing_before_init_is_legal_but_missing_after_init_is_blocked(scope):
    parent, plan = scope
    assert not (parent / plan["run_id"]).exists()
    artifact, budget = initialized(scope)
    (artifact / "vectors.db").rmdir()
    with pytest.raises(backend.Stop, match="^M5_STORAGE_PATH_MISSING$"):
        check(scope, budget)


@pytest.mark.parametrize("relative", [
    "historical.db", "collections/old/schema.json", "databases/old/backup",
    "collections/rag_qwen_1024_v1/wal/wal_data_000001.arrow",
    "collections/rag_qwen_1024_v1/data_000001_000001.parquet",
])
def test_historical_data_is_blocked_and_preserved(scope, relative):
    artifact, budget = initialized(scope)
    history = artifact / "vectors.db" / relative
    history.parent.mkdir(parents=True, exist_ok=True)
    history.write_text("fictional historical evidence")
    before = history.read_bytes()
    with pytest.raises(backend.Stop, match="^M5_RESOURCE_ALREADY_EXISTS$"):
        check(scope, budget)
    assert history.read_bytes() == before


def test_regular_file_cannot_replace_configured_directory(scope):
    artifact, budget = initialized(scope)
    vector = artifact / "vectors.db"
    vector.rmdir()
    vector.write_text("fictional legacy file storage")
    with pytest.raises(backend.Stop, match="^M5_STORAGE_TYPE_INVALID$"):
        check(scope, budget)
    assert vector.is_file()


@pytest.mark.parametrize("field,value", [("vector_storage_type", "file"), ("milvus_lite_version", "old")])
def test_unsupported_storage_config_blocks_before_reservation(scope, field, value):
    parent, plan = scope
    plan[field] = value
    with pytest.raises(backend.Stop, match="^M5_STORAGE_TYPE_INVALID$"):
        preflight.claim_artifact(parent, plan)
    assert list(parent.iterdir()) == []


@pytest.mark.parametrize("location", ["vector", "uploads", "marker", "ancestor", "child", "dangling"])
def test_simulated_symlink_blocks_before_read_or_traversal(scope, monkeypatch, location):
    artifact, budget = initialized(scope, True)
    targets = {"vector": artifact / "vectors.db", "uploads": artifact / "uploads",
               "marker": artifact / "preflight-owner.json", "ancestor": artifact.parent,
               "child": artifact / "vectors.db/LOCK", "dangling": artifact / "vectors.db"}
    target = targets[location]
    if location == "dangling":
        # No exists() call is allowed before the link check.
        monkeypatch.setattr(Path, "exists", lambda self: pytest.fail("Followed dangling link") if self == target else True)
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda self: self == target or original(self))
    with pytest.raises(backend.Stop, match="^M5_PATH_LINK_FORBIDDEN$"):
        check(scope, budget)


def test_simulated_windows_junction_blocks(scope, monkeypatch):
    artifact, budget = initialized(scope)
    original = Path.is_junction
    monkeypatch.setattr(Path, "is_junction", lambda self: self == artifact or original(self))
    with pytest.raises(backend.Stop, match="^M5_PATH_LINK_FORBIDDEN$"):
        check(scope, budget)


def test_scope_escape_is_rejected(scope):
    parent, plan = scope
    with pytest.raises(backend.Stop, match="^M5_PATH_OUTSIDE_SCOPE$"):
        preflight.checked_path(parent / ".." / "escape", parent)
    with pytest.raises(backend.Stop, match="^M5_PATH_OUTSIDE_SCOPE$"):
        preflight.checked_path(parent.parent / "escape", parent)


@pytest.mark.parametrize("owned", [False, True])
def test_existing_empty_or_owned_run_never_reused(scope, owned):
    parent, plan = scope
    if owned:
        artifact, _ = initialized(scope)
    else:
        artifact = parent / plan["run_id"]
        artifact.mkdir()
    before = set(artifact.iterdir())
    with pytest.raises(backend.Stop, match="^M5_RESOURCE_ALREADY_EXISTS$"):
        preflight.claim_artifact(parent, plan)
    assert set(artifact.iterdir()) == before


def test_wrong_owner_blocks_initialization_and_cleanup_ownership(scope):
    artifact, budget = initialized(scope)
    marker = artifact / "preflight-owner.json"
    marker.write_text('{"approval_id":"other","run_id":"abcdef123456"}')
    for action in (lambda: check(scope, budget), lambda: preflight.check_owned(*scope)):
        with pytest.raises(backend.Stop, match="^M5_RESOURCE_OWNERSHIP_ERROR$"):
            action()


@pytest.mark.parametrize("fault", ["table_rows", "vector_rows", "uploads", "ledger", "extra_file"])
def test_nonempty_initial_state_is_not_mistaken_for_initialization_metadata(scope, fault):
    artifact, budget = initialized(scope)
    rows, vector_rows = dict(ROWS), 0
    code = "M5_INITIAL_STATE_CHECK_FAILED"
    if fault == "table_rows":
        rows["documents"] = 1
    elif fault == "vector_rows":
        vector_rows = 1
    elif fault == "uploads":
        (artifact / "uploads/old.txt").write_text("fictional old upload")
        code = "M5_RESOURCE_ALREADY_EXISTS"
    elif fault == "extra_file":
        (artifact / "old-audit.json").write_text("{}")
        code = "M5_RESOURCE_ALREADY_EXISTS"
    else:
        (artifact / "ledger.json").write_text('{"calls":[{}]}')
    with pytest.raises(backend.Stop, match="^" + code + "$"):
        check(scope, budget, rows, vector_rows)


def test_full_offline_preflight_then_original_request_budget(scope):
    artifact, budget = initialized(scope, True)
    assert check(scope, budget)["model_requests"] == 0
    calls = []
    def fake_transport(model, path, body, code):
        calls.append(path)
        return {"usage": {"prompt_tokens": 1, "completion_tokens": 1 if path == "/chat/completions" else 0},
                "choices": [{"finish_reason": "stop", "message": {"content": "fictional"}}]}
    budget.reserve_post("upload")
    for index, question in enumerate(["fictional context", backend.QUESTION]):
        if index == 1:
            budget.reserve_post("message")
        budget.call(fake_transport, None, "/embeddings",
                    {"model": "text-embedding-v4", "input": [question], "dimensions": 1024}, "FAKE")
    request = {"model": "qwen-plus", "messages": [
        {"role": "system", "content": "fictional"},
        {"role": "user", "content": json.dumps({"question": backend.QUESTION,
          "untrusted_evidence": [{"source_id": 1, "text": "fictional context"}]})}]}
    budget.call(fake_transport, None, "/chat/completions", request, "FAKE")
    with pytest.raises(backend.Stop):
        budget.call(fake_transport, None, "/chat/completions", request, "FAKE")
    assert calls == ["/embeddings", "/embeddings", "/chat/completions"]
    assert budget.state["upload_posts"] == budget.state["message_posts"] == 1
    assert budget.state["status"] == "STOPPED"


def test_original_output_guard_and_model_budget_unchanged_and_startup_hook_precedes_yield():
    baseline = json.loads((ROOT / "data/m5-storage-preflight-fix/baseline.json").read_text(encoding="utf-8"))
    for relative in ["frontend/scripts/run-m5-browser.mjs", "frontend/scripts/m5-output-gate.mjs",
                     "frontend/playwright.m5.real.config.ts", "frontend/tests/m5-real.spec.ts"]:
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == baseline["preserved_files"][relative]
    source = (ROOT / "scripts/m5_browser_backend.py").read_text(encoding="utf-8")
    budget = source[source.index("class ModelBudget:"):source.index("\ndef serve(")]
    assert hashlib.sha256(budget.encode()).hexdigest() == baseline["model_budget_source_sha256_lf"]
    startup = source[source.index("async def guarded_lifespan"):source.index("app.router.lifespan_context = guarded_lifespan")]
    assert startup.index("get_vectors(app.state)") < startup.index("check_initialized(") < startup.index("yield")


@pytest.mark.parametrize("field,value", [
    ("run_id", "../other"), ("schema", "public"),
    ("artifact_dir", "D:/host-data-is-not-container-data"),
])
def test_schema_and_mount_scope_blocks_before_writes(scope, field, value):
    parent, plan = scope
    plan[field] = value
    with pytest.raises(backend.Stop, match="^INVALID_SCOPE$"):
        preflight.claim_artifact(parent, plan)
    assert list(parent.iterdir()) == []
