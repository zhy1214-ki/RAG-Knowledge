"""New offline key-loader checks only; never reads the project's real dotenv files."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import traceback
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "real_rag_acceptance.py"


@pytest.fixture
def runner(monkeypatch):
    spec = importlib.util.spec_from_file_location("real_rag_keys_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Stub reads instead of inspecting/inheriting any real process secret.
    monkeypatch.setattr(module.os, "getenv", lambda name, default="": default)
    return module


def test_process_environment_wins_without_reading_files(runner, monkeypatch, tmp_path):
    monkeypatch.setattr(runner.os, "getenv", lambda name, default="": "fictional-process-token")
    monkeypatch.setattr(runner, "dotenv_values", lambda *a, **k: pytest.fail("Unexpected file read"))
    assert runner.load_key(tmp_path / "missing-raw", tmp_path / "missing-dotenv") == "fictional-process-token"


def test_dotenv_literal_value_and_priority(runner, tmp_path, monkeypatch):
    dotenv = tmp_path / "synthetic.env"
    literal = "fictional-" + chr(36) + "{UNCHANGED}-token"
    dotenv.write_text('DASHSCOPE_API_KEY="' + literal + '"\n', encoding="utf-8-sig")
    raw = tmp_path / "raw.key"
    raw.write_text("fictional-raw-token", encoding="utf-8")
    actual_parser = runner.dotenv_values
    calls = []
    def parse(*args, **kwargs):
        calls.append(kwargs["interpolate"])
        return actual_parser(*args, **kwargs)
    monkeypatch.setattr(runner, "dotenv_values", parse)
    assert runner.load_key(raw, dotenv) == literal
    assert calls == [False]


def test_empty_process_environment_falls_back(runner, monkeypatch, tmp_path):
    monkeypatch.setattr(runner.os, "getenv", lambda name, default="": "  ")
    dotenv = tmp_path / "synthetic.env"
    dotenv.write_text("DASHSCOPE_API_KEY=fictional-env-file-token\n", encoding="utf-8")
    assert runner.load_key(key_env_file=dotenv) == "fictional-env-file-token"


def test_raw_file_compatibility(runner, tmp_path):
    raw = tmp_path / "raw.key"
    raw.write_text("fictional-legacy-token\n", encoding="utf-8")
    assert runner.load_key(key_file=raw) == "fictional-legacy-token"


@pytest.mark.parametrize("case,code", [
    ("none", "KEY_REQUIRED"),
    ("missing_env", "KEY_ENV_FILE_NOT_FOUND"),
    ("missing_variable", "KEY_ENV_VARIABLE_MISSING"),
    ("bare_variable", "KEY_ENV_VALUE_EMPTY"),
    ("empty_variable", "KEY_ENV_VALUE_EMPTY"),
    ("blank_variable", "KEY_ENV_VALUE_EMPTY"),
    ("missing_raw", "KEY_FILE_NOT_FOUND"),
    ("empty_raw", "KEY_FILE_EMPTY_OR_INVALID"),
    ("multiline_raw", "KEY_FILE_EMPTY_OR_INVALID"),
])
def test_missing_or_invalid_inputs_stop_safely(runner, tmp_path, case, code, capsys, caplog):
    env = tmp_path / "synthetic.env"
    raw = tmp_path / "raw.key"
    kwargs = {}
    content = {
        "missing_variable": "UNRELATED=fictional-unrelated-token\n",
        "bare_variable": "DASHSCOPE_API_KEY\n",
        "empty_variable": "DASHSCOPE_API_KEY=\n",
        "blank_variable": 'DASHSCOPE_API_KEY="  "\n',
    }
    if case in content:
        env.write_text(content[case], encoding="utf-8")
        kwargs = {"key_env_file": env, "key_file": raw}
        raw.write_text("fictional-legacy-token", encoding="utf-8")
    elif case == "missing_env":
        kwargs = {"key_env_file": env}
    elif case == "missing_raw":
        kwargs = {"key_file": raw}
    elif case in {"empty_raw", "multiline_raw"}:
        raw.write_text("" if case == "empty_raw" else "fictional-token\nsecond-line", encoding="utf-8")
        kwargs = {"key_file": raw}
    with pytest.raises(runner.Stop) as caught:
        runner.load_key(**kwargs)
    assert str(caught.value) == code
    output = capsys.readouterr()
    assert "fictional" not in output.out + output.err + caplog.text + str(caught.value)


def test_invalid_process_value_does_not_fall_back(runner, monkeypatch):
    monkeypatch.setattr(runner.os, "getenv", lambda name, default="": "fictional-token\nsecond-line")
    with pytest.raises(runner.Stop, match="^KEY_ENVIRONMENT_INVALID$"):
        runner.load_key()


@pytest.mark.parametrize("source", ["dotenv", "raw"])
def test_read_errors_do_not_disclose_secret(runner, monkeypatch, tmp_path, source, capsys, caplog):
    path = tmp_path / "synthetic.key"
    path.write_text("fictional-token", encoding="utf-8")
    marker = "fictional-error-content-must-stay-private"
    def fail(*args, **kwargs):
        raise OSError(marker)
    if source == "dotenv":
        monkeypatch.setattr(runner, "dotenv_values", fail)
        kwargs, code = {"key_env_file": path}, "KEY_ENV_FILE_READ_ERROR"
    else:
        monkeypatch.setattr(Path, "read_text", fail)
        kwargs, code = {"key_file": path}, "KEY_FILE_READ_ERROR"
    with pytest.raises(runner.Stop) as caught:
        runner.load_key(**kwargs)
    assert str(caught.value) == code
    assert marker not in "".join(traceback.format_exception(caught.type, caught.value, caught.tb))
    output = capsys.readouterr()
    assert marker not in output.out + output.err + caplog.text


@pytest.mark.parametrize("option", ["--key-file", "--key-env-file"])
def test_cli_accepts_both_interfaces_without_loading_keys(runner, monkeypatch, option):
    calls = []
    monkeypatch.setattr(runner, "prepare", lambda *args: calls.append("offline"))
    monkeypatch.setattr(runner.sys, "argv", ["real_rag_acceptance.py", "--prepare", option, "fictional-not-read"])
    assert runner.main() == 0 and calls == ["offline"]


@pytest.mark.parametrize("case,code", [
    ("old_approval", "EXPLICIT_APPROVAL_ARGUMENT_REQUIRED"),
    ("old_hash", "REVIEWED_RUNNER_CHANGED"),
])
def test_old_approval_or_hash_blocks_before_key_access(runner, monkeypatch, case, code):
    plan = {"run_id": "38f26eee9cf5", "approval_id": "38f26eee9cf5-key-env-v2",
            "runner_sha256": "obsolete-hash"}
    args = SimpleNamespace(approve=plan["run_id"] if case == "old_approval" else plan["approval_id"])
    monkeypatch.setattr(runner, "load_key", lambda *a, **k: pytest.fail("Key read before approval/hash checks"))
    with pytest.raises(runner.Stop, match="^" + code + "$"):
        runner.execute(args, plan)
