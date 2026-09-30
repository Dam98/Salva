import time

from fastapi.testclient import TestClient


def test_example_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("ALINEA_CONFIG", str(tmp_path / "cfg.json"))
    import importlib

    import alinea.server as server

    importlib.reload(server)
    c = TestClient(server.app)
    assert c.get("/").status_code == 200
    s = c.get("/api/settings").json()
    assert s["has_example"] and not s["has_llama_key"]
    job = c.post("/api/example").json()["job_id"]
    for _ in range(100):
        j = c.get(f"/api/jobs/{job}").json()
        if j["status"] != "running":
            break
        time.sleep(0.1)
    assert j["status"] == "done", j
    plan = j["result"]["plan"]
    out = c.post(f"/api/jobs/{job}/generate", json={"plan": plan, "settings": {"part_name": "X1"}}).json()
    assert "PART NAME  : X1" in out["program"] and out["stats"]["hits"] > 0
    # le modifiche della revisione vengono rispettate
    for it in plan["items"]:
        it["enabled"] = False
    out2 = c.post(f"/api/jobs/{job}/generate", json={"plan": plan}).json()
    assert out2["stats"]["dimensions"] == 0
