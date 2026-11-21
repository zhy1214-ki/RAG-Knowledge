from conftest import login


def test_crud(client, headers):
    row = client.post("/api/knowledge-bases", headers=headers, json={"name": "团队手册", "description": "测试"})
    assert row.status_code == 201
    kb = row.json()["data"]["id"]
    assert len(client.get("/api/knowledge-bases", headers=headers).json()["data"]) == 1
    assert client.put(f"/api/knowledge-bases/{kb}", headers=headers, json={"name": "新手册"}).json()["data"]["name"] == "新手册"
    assert client.get(f"/api/knowledge-bases/{kb}", headers=headers).status_code == 200
    assert client.delete(f"/api/knowledge-bases/{kb}", headers=headers).status_code == 200
    assert client.get(f"/api/knowledge-bases/{kb}", headers=headers).status_code == 404


def test_isolation_and_validation(client, headers):
    kb = client.post("/api/knowledge-bases", headers=headers, json={"name": "私人"}).json()["data"]["id"]
    other = login(client, "other")
    assert client.get(f"/api/knowledge-bases/{kb}", headers=other).status_code == 404
    assert client.get("/api/knowledge-bases", headers=other).json()["data"] == []
    assert client.get("/api/knowledge-bases").status_code == 401
    bad = client.post("/api/knowledge-bases", headers=headers, json={"name": ""})
    assert bad.status_code == 422 and bad.json()["code"] == "VALIDATION_ERROR"


def test_conflict_and_openapi(client, headers):
    for expected in (201, 409):
        assert client.post("/api/knowledge-bases", headers=headers, json={"name": "重复"}).status_code == expected
    assert "/api/knowledge-bases" in client.get("/openapi.json").json()["paths"]
    assert client.get("/api/health").json()["data"]["status"] == "ok"
