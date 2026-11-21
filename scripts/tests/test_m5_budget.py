"""Only M5's new request gate; no application settings, database or real credentials."""
import importlib.util
from pathlib import Path
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "m5_browser_backend.py"


@pytest.fixture
def module():
    spec = importlib.util.spec_from_file_location("m5_guard_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def body(module, index):
    if index < 2:
        return "/embeddings", {"model": "text-embedding-v4", "input": ["fictional context" if index == 0 else module.QUESTION], "dimensions": 1024}
    return "/chat/completions", {"model": "qwen-plus", "messages": [
        {"role":"system","content":"fictional system"},
        {"role":"user","content":module.json.dumps({"question":module.QUESTION,"untrusted_evidence":[{"source_id":1,"text":"fictional context"}]})}]}


def fake_call(calls):
    def call(model, path, request, code):
        calls.append((path, request))
        return {"usage":{"prompt_tokens":1,"completion_tokens":1 if path=="/chat/completions" else 0},
                "choices":[{"finish_reason":"stop","message":{"content":"fictional"}}]}
    return call


def test_three_requests_output_caps_and_no_fourth(module, tmp_path):
    guard = module.ModelBudget(tmp_path/"ledger.json", "fictional context")
    calls=[]
    for i in range(3):
        path, request=body(module,i)
        guard.call(fake_call(calls), None, path, request, "FAKE")
    assert len(calls)==3
    assert calls[-1][1]["max_tokens"]==256 and calls[-1][1]["enable_thinking"] is False
    with pytest.raises(module.Stop):
        guard.call(fake_call(calls),None,*body(module,2),"FAKE")
    assert len(calls)==3 and guard.state["status"]=="STOPPED"


@pytest.mark.parametrize("kind", ["upload","message"])
def test_duplicate_post_latches_stop(module,tmp_path,kind):
    guard=module.ModelBudget(tmp_path/"ledger.json","fictional context")
    guard.reserve_post(kind)
    with pytest.raises(module.Stop):guard.reserve_post(kind)
    calls=[]
    with pytest.raises(module.Stop):guard.call(fake_call(calls),None,*body(module,0),"FAKE")
    assert calls==[] and guard.state["status"]=="STOPPED"


def test_timeout_consumes_one_attempt_and_never_retries(module,tmp_path,capsys):
    guard=module.ModelBudget(tmp_path/"ledger.json","fictional context")
    calls=[]
    def fail(*args):
        calls.append(1)
        raise TimeoutError("fictional secret must not escape")
    with pytest.raises(module.Stop) as error:guard.call(fail,None,*body(module,0),"FAKE")
    with pytest.raises(module.Stop):guard.call(fail,None,*body(module,0),"FAKE")
    assert len(calls)==1 and len(guard.state["calls"])==1
    assert str(error.value)=="ACCEPTANCE_STOPPED"
    text=(tmp_path/"ledger.json").read_text()
    assert "fictional secret" not in text+capsys.readouterr().out+str(error.value)


def test_restart_cannot_reset_ledger(module,tmp_path):
    path=tmp_path/"ledger.json"
    module.ModelBudget(path,"fictional context")
    with pytest.raises(FileExistsError):module.ModelBudget(path,"fictional context")


@pytest.mark.parametrize("case",["wrong_question","wrong_dimension","wrong_order"])
def test_unplanned_calls_stop_before_transport(module,tmp_path,case):
    guard=module.ModelBudget(tmp_path/"ledger.json","fictional context")
    path,request=body(module,0)
    if case=="wrong_question":request["input"]=["unreviewed text"]
    elif case=="wrong_dimension":request["dimensions"]=768
    else:path="/chat/completions"
    calls=[]
    with pytest.raises(module.Stop):guard.call(fake_call(calls),None,path,request,"FAKE")
    assert calls==[] and guard.state["status"]=="STOPPED"


def test_mutation_failure_stops_remaining_models(module,tmp_path):
    guard=module.ModelBudget(tmp_path/"ledger.json","fictional context")
    calls=[]
    guard.call(fake_call(calls),None,*body(module,0),"FAKE")
    guard.halt("API_MUTATION_FAILED")
    with pytest.raises(module.Stop):guard.call(fake_call(calls),None,*body(module,1),"FAKE")
    assert len(calls)==1


def test_missing_usage_stops_without_resubmit(module,tmp_path):
    guard=module.ModelBudget(tmp_path/"ledger.json","fictional context")
    with pytest.raises(module.Stop):guard.call(lambda *args:{},None,*body(module,0),"FAKE")
    assert len(guard.state["calls"])==1 and guard.state["status"]=="STOPPED"


def test_default_cli_never_starts_server(module,monkeypatch,capsys):
    monkeypatch.setattr(module.sys,"argv",["m5_browser_backend.py"])
    monkeypatch.setattr(module,"serve",lambda *args:pytest.fail("Unexpected server startup"))
    assert module.main()==0
    assert "OFFLINE_ONLY" in capsys.readouterr().out


def test_unapproved_server_blocks_before_key_read(module,monkeypatch,tmp_path):
    from types import SimpleNamespace
    plan=tmp_path/"plan.json"
    plan.write_text('{"approval_id":"fictional-new-m5-approval"}',encoding="utf-8")
    monkeypatch.setattr(module,"load_key",lambda *a,**k:pytest.fail("Unexpected credential read"))
    with pytest.raises(module.Stop,match="^EXPLICIT_M5_APPROVAL_REQUIRED$"):
        module.serve(SimpleNamespace(plan=plan,approve="old-approval"))
