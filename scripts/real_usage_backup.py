"""Offline snapshot validation only: never invokes Docker or opens a live database."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile

ROOT = Path(__file__).resolve().parents[1]
FILES = ("postgres.dump", "app-data.tar", "audit-data.tar")


def check(condition, code):
    if not condition: raise ValueError(code)


def safe_archive(path):
    with tarfile.open(path, "r") as archive:
        for entry in archive:
            normalized = entry.name.replace("\\", "/")
            name = PurePosixPath(normalized)
            check(not name.is_absolute() and ".." not in name.parts and ":" not in normalized, "R1_UNSAFE_ARCHIVE_PATH")
            check(entry.isfile() or entry.isdir(), "R1_UNSAFE_ARCHIVE_ENTRY")


def inspect_files(folder):
    check(folder.is_dir() and not folder.is_symlink(), "R1_SNAPSHOT_PATH_INVALID")
    result = {}
    for name in FILES:
        path = folder / name
        check(path.is_file() and not path.is_symlink(), "R1_SNAPSHOT_FILE_INVALID")
        if name.endswith(".tar"): safe_archive(path)
        else:
            with path.open("rb") as f: check(f.read(5) == b"PGDMP", "R1_POSTGRES_DUMP_INVALID")
        with path.open("rb") as source:
            result[name] = hashlib.file_digest(source, "sha256").hexdigest()
    return result


def make_manifest(folder):
    hashes = inspect_files(folder)
    marker = json.loads((folder / "quiesced.json").read_text(encoding="utf-8"))
    check(marker == {"project": "rag-knowledge-real", "writers_stopped": True}, "R1_QUIESCENCE_RECORD_REQUIRED")
    manifest = {"project": "rag-knowledge-real", "files": hashes,
        "credential_files_included": False, "restore_verified": False}
    with (folder / "manifest.json").open("x", encoding="utf-8") as target:
        json.dump(manifest, target, indent=2)
    return manifest


def verify(folder):
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    check(manifest["project"] == "rag-knowledge-real", "R1_BACKUP_OWNER_MISMATCH")
    check(set(manifest["files"]) == set(FILES), "R1_BACKUP_FILE_SET_INVALID")
    check(inspect_files(folder) == manifest["files"], "R1_BACKUP_HASH_MISMATCH")
    return {"status": "PASS", "files": len(FILES), "restore_runtime": "NOT_VERIFIED"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["manifest", "verify"])
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()
    try:
        folder = args.snapshot
        scope = ROOT / "data/real-usage-backups"
        for candidate in (scope, scope.parent):
            check(not candidate.is_symlink() and not (hasattr(candidate, "is_junction") and candidate.is_junction()), "R1_BACKUP_LINKED_SCOPE")
        check(folder.is_absolute() and not folder.is_symlink()
            and folder.resolve().is_relative_to(scope.resolve()), "R1_BACKUP_OUTSIDE_PROJECT_SCOPE")
        print(json.dumps(make_manifest(folder) if args.action == "manifest" else verify(folder)))
    except Exception:
        print("R1_BACKUP_VALIDATION_FAILED")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())