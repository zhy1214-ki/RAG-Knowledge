"""Project-only synthetic HTTP acceptance. No real model requests."""
import argparse
from pathlib import Path
from time import monotonic, sleep
from uuid import uuid4
import httpx

parser=argparse.ArgumentParser()
parser.add_argument("--base-url",default="http://127.0.0.1:8080")
args=parser.parse_args()
root=Path(__file__).resolve().parents[1]
with httpx.Client(base_url=args.base_url,timeout=90,trust_env=False) as client:
    def call(method,path,**kwargs):
        response=client.request(method,"/api"+path,**kwargs)
        assert response.status_code<300, (path,response.status_code,response.json().get("code"))
        return response.json()["data"]
    health=call("GET","/health")
    assert health["model_backend"]=="mock", "This script is authorized only for Mock mode"
    username="smoke_"+uuid4().hex[:12]
    password=uuid4().hex
    call("POST","/auth/register",json={"username":username,"password":password})
    token=call("POST","/auth/login",json={"username":username,"password":password})["access_token"]
    client.headers["Authorization"]="Bearer "+token
    kb=call("POST","/knowledge-bases",json={"name":"Compose 合成验收"})["id"]
    try:
        for filename in ("travel-policy.docx","travel-policy.pdf"):
            with (root/"samples"/filename).open("rb") as f:
                row=call("POST",f"/knowledge-bases/{kb}/documents",files={"file":(filename,f)})
            doc=row["id"]
            deadline=monotonic()+60
            while monotonic()<deadline:
                status=call("GET",f"/knowledge-bases/{kb}/documents/{doc}")
                if status["status"] in {"indexed","failed"}:break
                sleep(.3)
            assert status["status"]=="indexed",(status["status"],status["error_code"])
        session=call("POST","/sessions",json={"knowledge_base_id":kb})["id"]
        answer=call("POST",f"/sessions/{session}/messages",json={"question":"差旅报销需要多久提交？"})
        assert "三十天" in answer["content"] and answer["citations"]
        assert len(call("GET",f"/sessions/{session}/messages"))==2
        docs=call("GET",f"/knowledge-bases/{kb}/documents")
        for doc in docs:call("DELETE",f"/knowledge-bases/{kb}/documents/{doc['id']}")
        assert call("POST",f"/knowledge-bases/{kb}/search",json={"question":"差旅报销"})==[]
        print("PASS: Compose HTTP / PostgreSQL / DOCX+PDF / Milvus / Mock RAG / citations / history / deletion")
    finally:
        call("DELETE",f"/knowledge-bases/{kb}")
        # Leaves only this synthetic account; no documents, vectors or chats remain.
