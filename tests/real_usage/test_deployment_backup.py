import importlib.util
import io
import sys
import json
from pathlib import Path
import tarfile
from types import SimpleNamespace
import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable
import yaml
from app.real_usage.guard import GuardBase
import real_usage_backup as backup
import real_usage_runtime as runtime

ROOT=Path(__file__).resolve().parents[2]


def test_compose_isolation_persistence_and_no_secret_in_environment():
    config=yaml.safe_load((ROOT/"deploy/real-usage/compose.yml").read_text(encoding="utf-8"))
    assert config["name"]=="rag-knowledge-real"
    assert config["networks"]=={"default":{}}
    assert set(config["services"])=={"real-postgres","real-backend","real-frontend"}
    assert config["services"]["real-frontend"]["ports"]==["127.0.0.1:8081:80"]
    assert all(s["profiles"]==["real-usage"] for s in config["services"].values())
    assert not any("ports" in config["services"][n] for n in ["real-postgres","real-backend"])
    backend=config["services"]["real-backend"]
    assert backend["environment"]["MODEL_BACKEND"]=="qwen"
    assert "DASHSCOPE_API_KEY" not in backend["environment"] and "DATABASE_URL" not in backend["environment"]
    mount=next(m for m in backend["volumes"] if isinstance(m,dict))
    assert mount["source"]=="../../backend/.env" and mount["read_only"] and not mount["bind"]["create_host_path"]
    assert set(config["volumes"])=={"real_pg_data","real_app_data","real_audit_data"}
    assert not any(v.get("external") for v in config["volumes"].values() if isinstance(v,dict))
    docker=(ROOT/"deploy/real-usage/backend.Dockerfile").read_text(encoding="utf-8")
    assert "COPY backend/app" in docker and ".env" not in docker
    assert "**/.env" in (ROOT/".dockerignore").read_text(encoding="utf-8")


def test_runtime_approval_blocks_before_credential_loader(monkeypatch,capsys):
    monkeypatch.setattr(runtime.sys,"argv",["real_usage_runtime.py","serve","--runtime-mode","real"])
    monkeypatch.setattr(runtime,"load_key",lambda *a,**k:pytest.fail("Credential loader before approval"))
    monkeypatch.delenv("R1_APPROVAL_ID",raising=False);monkeypatch.delenv("R1_APPROVAL_SHA256",raising=False)
    assert runtime.main()==2
    assert "R1_EXPLICIT_DEPLOYMENT_APPROVAL_REQUIRED" in capsys.readouterr().err


def test_safe_reuse_of_key_loader_with_fictional_dotenv(tmp_path,monkeypatch):
    import real_rag_acceptance
    monkeypatch.setattr(real_rag_acceptance.os,"getenv",lambda *args:"")
    path=tmp_path/"fictional.env"
    path.write_text("DASHSCOPE_API_KEY='offline-"+chr(36)+"{LITERAL}'\n",encoding="utf-8")
    loaded=runtime.load_key(key_env_file=path)
    assert loaded.endswith(chr(36)+"{LITERAL}") and len(loaded)>10


def test_real_only_migration_matches_models_and_compiles_for_postgresql():
    path=ROOT/"backend/real_usage_migrations/versions/r1_001_guard.py"
    spec=importlib.util.spec_from_file_location("r1_guard_migration",path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    metadata=sa.MetaData()
    def create(name,*columns):sa.Table(name,metadata,*columns)
    module.op=SimpleNamespace(create_table=create,create_index=lambda *a:None)
    module.upgrade()
    # The additive R4 migration, not the frozen R1 revision, provides clock fields.
    spec=importlib.util.spec_from_file_location("r4_clock_migration",ROOT/"backend/real_usage_migrations/versions/r4_002_clock.py")
    clock=importlib.util.module_from_spec(spec);spec.loader.exec_module(clock)
    clock.op=SimpleNamespace(add_column=lambda name,column: metadata.tables[name].append_column(column))
    clock.upgrade()
    assert clock.down_revision=="r1_001"
    assert module.down_revision=="001" and set(metadata.tables)==set(GuardBase.metadata.tables)
    for name,table in metadata.tables.items():
        expected=GuardBase.metadata.tables[name]
        assert [(c.name,str(c.type),c.nullable,c.primary_key) for c in table.columns]==[(c.name,str(c.type),c.nullable,c.primary_key) for c in expected.columns]
        assert "CREATE TABLE" in str(CreateTable(table).compile(dialect=postgresql.dialect()))


def make_snapshot(folder):
    folder.mkdir()
    (folder/"postgres.dump").write_bytes(b"PGDMP fictional offline fixture")
    for name in ["app-data.tar","audit-data.tar"]:
        with tarfile.open(folder/name,"w") as archive:
            data=b"synthetic-only";entry=tarfile.TarInfo("sample.txt");entry.size=len(data)
            archive.addfile(entry,io.BytesIO(data))
    (folder/"quiesced.json").write_text(json.dumps({"project":"rag-knowledge-real","writers_stopped":True}),encoding="utf-8")


def test_backup_hash_verification_and_corruption_detection(tmp_path):
    folder=tmp_path/"snapshot";make_snapshot(folder)
    backup.make_manifest(folder)
    assert backup.verify(folder)["restore_runtime"]=="NOT_VERIFIED"
    (folder/"postgres.dump").write_bytes(b"PGDMP corrupted fixture")
    with pytest.raises(ValueError,match="R1_BACKUP_HASH_MISMATCH"):backup.verify(folder)


@pytest.mark.parametrize("name",["../escape","/absolute","C:/outside"])
def test_backup_rejects_escaping_archive_members(tmp_path,name):
    archive=tmp_path/"unsafe.tar"
    with tarfile.open(archive,"w") as out:
        entry=tarfile.TarInfo(name);entry.size=1;out.addfile(entry,io.BytesIO(b"x"))
    with pytest.raises(ValueError,match="R1_UNSAFE_ARCHIVE_PATH"):backup.safe_archive(archive)


def test_backup_rejects_symlink_members_and_wrong_owner(tmp_path):
    archive=tmp_path/"linked.tar"
    with tarfile.open(archive,"w") as out:
        entry=tarfile.TarInfo("link");entry.type=tarfile.SYMTYPE;entry.linkname="/outside";out.addfile(entry)
    with pytest.raises(ValueError,match="R1_UNSAFE_ARCHIVE_ENTRY"):backup.safe_archive(archive)
    folder=tmp_path/"snapshot";make_snapshot(folder);manifest=backup.make_manifest(folder)
    manifest["project"]="rag-knowledge"
    (folder/"manifest.json").write_text(json.dumps(manifest),encoding="utf-8")
    with pytest.raises(ValueError,match="R1_BACKUP_OWNER_MISMATCH"):backup.verify(folder)
def test_runtime_rejects_unapproved_limit_increase(settings):
    plan={"limits":{"max_calls_total":3,"daily_budget_cny":"0.01","max_output_tokens":256}}
    runtime.validate_limits(settings,plan)
    with pytest.raises(runtime.Stop,match="R1_APPROVED_LIMITS_MISMATCH"):
        runtime.validate_limits(settings.model_copy(update={"max_calls_total":0}),plan)


def test_backup_cli_cannot_escape_its_project_scope(tmp_path,monkeypatch,capsys):
    monkeypatch.setattr(sys,"argv",
        ["real_usage_backup.py","verify","--snapshot",str(tmp_path)])
    assert backup.main()==2
    assert "R1_BACKUP_VALIDATION_FAILED" in capsys.readouterr().out

def test_backup_cli_rejects_linked_scope(tmp_path,monkeypatch,capsys):
    monkeypatch.setattr(backup,"ROOT",tmp_path)
    scope=tmp_path/"data/real-usage-backups"
    original=Path.is_symlink
    monkeypatch.setattr(Path,"is_symlink",lambda path:path==scope or original(path))
    monkeypatch.setattr(sys,"argv",["real_usage_backup.py","verify","--snapshot",str(scope/"one")])
    assert backup.main()==2
    assert "R1_BACKUP_VALIDATION_FAILED" in capsys.readouterr().out
