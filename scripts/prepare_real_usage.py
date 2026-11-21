"""Preparation only. This script never invokes Docker, a model or a database."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets

ROOT = Path(__file__).resolve().parents[1]


def check_sources(runtime_mode, approval_file=None):
    from real_usage_runtime import approval_path, check_approval
    path = approval_path(runtime_mode, approval_file)
    plan = json.loads(path.read_text(encoding="utf-8"))
    check_approval(plan["approval_id"], hashlib.sha256(path.read_bytes()).hexdigest(), runtime_mode, path)
    for relative, expected in {**plan["runtime_files"], **plan["review_files"]}.items():
        if hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() != expected:
            raise ValueError("R1_REVIEWED_FILE_CHANGED")
    return {"approval_id": plan["approval_id"], "approval_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "artifact_hashes": "PASS", "runtime_mode": runtime_mode, "paid_calls_authorized": False,
        "credential_contents_read": False, "deployment_authorized": False, "services_started": False}


def init_secrets():
    folder = ROOT / "data/real-usage-secrets"
    for ancestor in [folder, folder.parent]:
        if ancestor.is_symlink() or (hasattr(ancestor, "is_junction") and ancestor.is_junction()):
            raise ValueError("R1_SECRET_DIRECTORY_LINK")
    folder.mkdir(parents=True, exist_ok=True)
    targets = [folder / "postgres_password", folder / "jwt_secret"]
    if any(path.exists() for path in targets): raise ValueError("R1_SECRET_ALREADY_EXISTS")
    for path in targets:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as target:
            target.write(secrets.token_urlsafe(48) + "\n")
    return {"created_files": 2, "values_printed": False, "windows_acl": "NOT_VERIFIED"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--init-secrets", action="store_true")
    parser.add_argument("--runtime-mode", default="")
    parser.add_argument("--approval-file", type=Path)
    args = parser.parse_args()
    try:
        from real_usage_runtime import approval_path
        approval_path(args.runtime_mode, args.approval_file)
        print(json.dumps(init_secrets() if args.init_secrets else check_sources(args.runtime_mode, args.approval_file)))
    except Exception:
        print("R1_PREPARATION_CHECK_FAILED")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())