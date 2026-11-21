"""Explicitly gated isolated runtime. Importing it never reads credential files."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))
from real_rag_acceptance import load_key, Stop


def approval_path(runtime_mode, approval_file=None):
    if runtime_mode not in {"infrastructure", "real"}:
        raise Stop("R2_RUNTIME_MODE_INVALID")
    path = Path(approval_file) if approval_file else Path(
        "deploy/real-usage/approval.infrastructure.json" if runtime_mode == "infrastructure"
        else "deploy/real-usage/approval.json")
    if not path.is_absolute():
        path = ROOT / path
    if path.is_symlink() or not path.resolve().is_relative_to((ROOT / "deploy/real-usage").resolve()):
        raise Stop("R1_ARTIFACT_PATH_INVALID")
    return path


def check_approval(approval_id, expected_sha, runtime_mode=None, approval_file=None):
    path = approval_path(runtime_mode, approval_file)
    if not approval_id or not expected_sha:
        raise Stop("R1_EXPLICIT_DEPLOYMENT_APPROVAL_REQUIRED")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha:
        raise Stop("R1_APPROVAL_HASH_MISMATCH")
    plan = json.loads(raw)
    if approval_id != plan["approval_id"] or plan["historical_model_requests"] != 6:
        raise Stop("R1_APPROVAL_ID_OR_HISTORY_MISMATCH")
    if (plan.get("runtime_mode") != runtime_mode
            or plan.get("paid_calls_authorized") is not (runtime_mode == "real")):
        raise Stop("R2_APPROVED_RUNTIME_MODE_MISMATCH")
    for relative, expected in plan["runtime_files"].items():
        name = Path(relative)
        if name.is_absolute() or ".." in name.parts:
            raise Stop("R1_ARTIFACT_PATH_INVALID")
        actual = ROOT / name
        if actual.is_symlink() or hashlib.sha256(actual.read_bytes()).hexdigest() != expected:
            raise Stop("R1_RUNTIME_ARTIFACT_MISMATCH")
    return plan


def validate_environment(runtime_mode):
    approval_path(runtime_mode)
    declared = os.environ.get("RAG_RUNTIME_MODE")
    if declared is not None and declared != runtime_mode:
        raise Stop("R2_RUNTIME_CONFIGURATION_CONFLICT")
    expected = {"MODEL_BACKEND": "mock" if runtime_mode == "infrastructure" else "qwen",
                "ALLOW_PAID_MODELS": "false" if runtime_mode == "infrastructure" else "true"}
    for name, value in expected.items():
        if name in os.environ and os.environ[name].lower() != value:
            raise Stop("R2_RUNTIME_CONFIGURATION_CONFLICT")
    if runtime_mode == "infrastructure":
        if "DASHSCOPE_API_KEY" in os.environ or Path("/run/secrets/model.env").exists():
            raise Stop("R2_INFRASTRUCTURE_KEY_INJECTION_FORBIDDEN")


def load_settings(runtime_mode):
    validate_environment(runtime_mode)
    from pydantic import SecretStr
    from app.real_usage.config import RealUsageSettings
    key = load_key(key_env_file=Path("/run/secrets/model.env")) if runtime_mode == "real" else ""
    return RealUsageSettings(_env_file=None, rag_runtime_mode=runtime_mode,
        model_backend="qwen" if runtime_mode == "real" else "mock",
        allow_paid_models=runtime_mode == "real",
        database_url=SecretStr(database_url()),
        jwt_secret=SecretStr(read_secret("/run/secrets/jwt_secret")), dashscope_api_key=SecretStr(key))


def read_secret(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise Stop("R1_SECRET_FILE_INVALID")
    value = path.read_text(encoding="utf-8-sig").strip()
    if not value or "\r" in value or "\n" in value:
        raise Stop("R1_SECRET_VALUE_INVALID")
    return value


def database_url():
    from sqlalchemy.engine import URL
    password = read_secret("/run/secrets/postgres_password")
    return URL.create("postgresql+psycopg", username="rag_real", password=password,
        host="real-postgres", port=5432, database="rag_personal_real").render_as_string(hide_password=False)


def validate_limits(cfg, plan):
    for name, expected in plan["limits"].items():
        if str(getattr(cfg, name)) != str(expected):
            raise Stop("R1_APPROVED_LIMITS_MISMATCH")


def serve(plan, runtime_mode):
    cfg = load_settings(runtime_mode)
    validate_limits(cfg, plan)
    from alembic import command
    from alembic.config import Config
    config = Config(str(ROOT / "backend/alembic.ini"))
    config.attributes["settings"] = cfg
    from app.models import Base
    from app.real_usage.guard import GuardBase
    config.attributes["target_metadata"] = [Base.metadata, GuardBase.metadata]
    config.set_main_option("version_locations", os.pathsep.join([str(ROOT / "backend/migrations/versions"), str(ROOT / "backend/real_usage_migrations/versions")]))
    command.upgrade(config, "head")
    from app.real_usage.application import create_real_app
    import uvicorn
    uvicorn.run(create_real_app(cfg), host="0.0.0.0", port=8000, workers=1, access_log=False)


def admin(acknowledge, acknowledge_clock=False):
    from sqlalchemy import select, func
    from app.core.db import make_database
    from app.real_usage.guard import GuardState, ModelCall, Operation, usage_windows, sample_clock, valid_clock_sample, persisted_time_floor
    engine, sessions = make_database(database_url())
    try:
        with sessions() as db:
            state = db.scalar(select(GuardState).where(GuardState.id == 1).with_for_update())
            if state is None: raise Stop("R1_USAGE_NOT_INITIALIZED")
            if acknowledge:
                if db.scalar(select(Operation.id).where(Operation.status == "RUNNING").limit(1)):
                    raise Stop("R1_OPERATION_STILL_RUNNING")
                if db.scalar(select(ModelCall.id).where(ModelCall.status == "SENT_UNCERTAIN").limit(1)):
                    raise Stop("R1_REQUEST_RESULT_STILL_UNCERTAIN")
                if state.reason == "CLOCK_REVIEW_REQUIRED" and not acknowledge_clock:
                    raise Stop("R4_EXPLICIT_CLOCK_ACK_REQUIRED")
                if acknowledge_clock:
                    import time
                    sample = sample_clock(time.time, time.monotonic)
                    floor = persisted_time_floor(db, state)
                    if floor is None or not valid_clock_sample(sample) or sample[0] < floor:
                        raise Stop("R4_CLOCK_BEFORE_PERSISTED_RECORD")
                    state.last_observed_at, state.clock_epoch = max(floor, sample[0]), state.clock_epoch + 1
                state.stopped, state.reason = False, ""
                db.commit()
                with Path("/audit/usage.jsonl").open("a", encoding="utf-8") as target:
                    target.write(json.dumps({"event": "OPERATOR_ACKNOWLEDGED_NO_REFUND", "clock_confirmed": acknowledge_clock}) + "\n")
            import time
            if persisted_time_floor(db, state) is None:
                raise Stop("R4_CLOCK_STATE_UNTRUSTED")
            window = usage_windows(state.last_observed_at if state.reason == "CLOCK_REVIEW_REQUIRED" else time.time())
            daily = (ModelCall.created_at >= window["day_start"], ModelCall.created_at < window["day_end"])
            monthly = (ModelCall.created_at >= window["month_start"], ModelCall.created_at < window["month_end"])
            print(json.dumps({"day_utc": window["day"], "month_utc": window["month"],
                "daily_reserved_cny": str(db.scalar(select(func.sum(ModelCall.charge_cny)).where(*daily)) or 0),
                "monthly_reserved_cny": str(db.scalar(select(func.sum(ModelCall.charge_cny)).where(*monthly)) or 0),
                "last_observed_at": state.last_observed_at, "clock_epoch": state.clock_epoch,
                "historical_baseline": state.historical_requests,
                "r1_reserved_attempts": db.scalar(select(func.count()).select_from(ModelCall)),
                "reserved_estimate_cny": str(db.scalar(select(func.sum(ModelCall.charge_cny))) or 0),
                "active_operations": db.scalar(select(func.count()).select_from(Operation).where(Operation.status == "RUNNING")),
                "uncertain_calls": db.scalar(select(func.count()).select_from(ModelCall).where(ModelCall.status != "VERIFIED")),
                "stopped": state.stopped, "reason": state.reason}))
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["serve", "status", "ack-stop"])
    parser.add_argument("--runtime-mode", default=os.getenv("RAG_RUNTIME_MODE", ""))
    parser.add_argument("--approval-file", type=Path)
    parser.add_argument("--approval-id", default=os.getenv("R1_APPROVAL_ID", ""))
    parser.add_argument("--approval-sha256", default=os.getenv("R1_APPROVAL_SHA256", ""))
    parser.add_argument("--acknowledge-uncertain-charges", action="store_true")
    parser.add_argument("--acknowledge-clock", action="store_true")
    args = parser.parse_args()
    try:
        validate_environment(args.runtime_mode)
        plan = check_approval(args.approval_id, args.approval_sha256, args.runtime_mode, args.approval_file)
        if args.action == "serve": serve(plan, args.runtime_mode)
        elif args.action == "status": admin(False)
        elif args.runtime_mode != "real": raise Stop("R2_INFRASTRUCTURE_MODEL_ADMIN_DISABLED")
        elif args.acknowledge_uncertain_charges: admin(True, args.acknowledge_clock)
        else: raise Stop("R1_OPERATOR_ACKNOWLEDGMENT_REQUIRED")
    except Exception as error:
        print(str(error) if isinstance(error, Stop) else "R1_RUNTIME_CONFIGURATION_OR_STORAGE_ERROR", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())