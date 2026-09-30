import importlib
import json
import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def web(monkeypatch, tmp_path):
    monkeypatch.setenv("ALINEA_WEB", "1")
    monkeypatch.setenv("ALINEA_PASSWORD", "segreta-123")
    monkeypatch.setenv("ALINEA_SECRET", "x" * 32)
    monkeypatch.setenv("LLAMA_CLOUD_API_KEY", "llx-server-key-000000")
    monkeypatch.setenv("ALINEA_CONFIG", str(tmp_path / "cfg.json"))
    import alinea.server as server

    importlib.reload(server)
    yield server
    for k in ("ALINEA_WEB", "ALINEA_PASSWORD", "ALINEA_SECRET", "LLAMA_CLOUD_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    importlib.reload(server)


def _wait(c, job):
    for _ in range(100):
        j = c.get(f"/api/jobs/{job}").json()
        if j["status"] != "running":
            return j
        time.sleep(0.1)
    return j


def test_password_required(web):
    c = TestClient(web.app)
    assert c.get("/healthz").status_code == 200
    r = c.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert c.get("/api/settings").status_code == 401
    assert c.post("/api/example").status_code == 401
    assert c.post("/api/login", json={"password": "sbagliata"}).status_code == 401
    assert c.post("/api/login", json={"password": "segreta-123"}).status_code == 200
    assert c.get("/").status_code == 200
    s = c.get("/api/settings").json()
    assert s["web"] and s["auth"] and s["has_llama_key"]
    assert "llx-server" not in json.dumps(s)          # la chiave non esce mai dal server
    assert c.post("/api/settings", json={"llama_api_key": "x"}).status_code == 403


def test_forged_cookie_rejected(web):
    c = TestClient(web.app)
    c.cookies.set(web.COOKIE, f"{int(time.time()) + 999}.deadbeef")
    assert c.get("/api/settings").status_code == 401


def test_login_rate_limit(web):
    c = TestClient(web.app)
    codes = [c.post("/api/login", json={"password": "no"}).status_code for _ in range(9)]
    assert codes[-1] == 429


def test_web_flow_with_user_settings(web):
    c = TestClient(web.app)
    c.post("/api/login", json={"password": "segreta-123"})
    job = c.post("/api/example", json={"settings": {"probe": "PROBE_X", "reader_mode": "pdf"}}).json()["job_id"]
    j = _wait(c, job)
    assert j["status"] == "done"
    out = c.post(f"/api/jobs/{job}/generate",
                 json={"plan": j["result"]["plan"], "settings": {"probe": "PROBE_X", "part_name": "P-9"}}).json()
    assert "LOADPROBE/PROBE_X" in out["program"] and "PART NAME  : P-9" in out["program"]


def test_upload_and_drawing_types(web):
    c = TestClient(web.app)
    c.post("/api/login", json={"password": "segreta-123"})
    ex = web.EXAMPLES
    with open(ex / "staffa.stp", "rb") as a, open(ex / "staffa_disegno.pdf", "rb") as b:
        job = c.post("/api/analyze", files={"cad": ("pezzo.stp", a), "drawing": ("dis.pdf", b)},
                     data={"part_name": "PZ"}).json()["job_id"]
    assert _wait(c, job)["status"] == "done"
    r = c.get(f"/api/jobs/{job}/drawing")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    # un file non-disegno non viene mai servito (niente HTML sullo stesso dominio)
    with open(ex / "staffa.stp", "rb") as a:
        job2 = c.post("/api/analyze", files={"cad": ("pezzo.stp", a), "drawing": ("x.html", b"<script>")}).json()["job_id"]
    _wait(c, job2)
    assert c.get(f"/api/jobs/{job2}/drawing").status_code == 404


def test_web_without_password_stays_closed(monkeypatch):
    monkeypatch.setenv("ALINEA_WEB", "1")
    monkeypatch.delenv("ALINEA_PASSWORD", raising=False)
    import alinea.server as server

    importlib.reload(server)
    try:
        c = TestClient(server.app)
        assert c.get("/healthz").status_code == 200
        r = c.get("/")
        assert r.status_code == 503 and "ALINEA_PASSWORD" in r.text
        assert c.post("/api/example").status_code == 503
    finally:
        monkeypatch.delenv("ALINEA_WEB", raising=False)
        importlib.reload(server)


def test_https_cookie_works_in_iframe(web):
    c = TestClient(web.app, base_url="https://esempio.hf.space")
    r = c.post("/api/login", json={"password": "segreta-123"})
    sc = r.headers["set-cookie"].lower()
    assert "samesite=none" in sc and "secure" in sc and "partitioned" in sc and "httponly" in sc
    assert "frame-ancestors" in r.headers["content-security-policy"]
    assert "x-frame-options" not in r.headers
