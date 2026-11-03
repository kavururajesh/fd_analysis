"""JSON API used by the React app (src/api/web.py)."""
import json

import pytest
from fastapi.testclient import TestClient

from src.api import web
from src.api.routes import create_app
from src.llm.offline import OfflineLLM
from src.service import FDService


@pytest.fixture()
def empty(store, files, monkeypatch):
    monkeypatch.setattr(web, "svc", FDService(store, OfflineLLM(), files))
    return TestClient(create_app())


@pytest.fixture()
def client(store, fixture_site, files, monkeypatch):
    svc = FDService(store, OfflineLLM(), files)
    ctx = svc.refresh()
    svc.approve(ctx.run_id)
    monkeypatch.setattr(web, "svc", svc)
    return TestClient(create_app())


def test_first_start_has_no_data_but_pages_still_load(empty):
    m = empty.get("/api/meta").json()
    assert m["has_data"] is False and m["pending_review"] == 0
    assert empty.get("/api/dashboard").status_code == 404
    assert empty.post("/api/chat", json={"question": "hi"}).json()["status"] == "no_data"
    s = empty.get("/api/ops/summary").json()
    assert s["manifest"] is None and s["runs"] == [] and s["files"] == []


def test_meta_and_dashboard(client):
    m = client.get("/api/meta").json()
    assert m["has_data"] and m["peers"] and "Sberbank corporate" not in m["peers"] and m["tenors"][0]["days"] == 7
    d = client.get("/api/dashboard", params={"amount": 10, "days": 90}).json()
    assert d["kpis"]["sber_rate"] == 7.0 and d["kpis"]["rank"] == 1 and d["kpis"]["led"] == 14 and d["kpis"]["points"] == 20
    assert {"lead_share", "ranking", "curve", "heatmap", "size", "history", "coverage", "source_types"} <= set(d["charts"])
    assert d["table"][0]["name"] == "Sberbank corporate" and d["findings"]
    json.dumps(d)                                                   # no NaN / numpy leaks


def test_dashboard_filters(client):
    peers = client.get("/api/meta").json()["peers"]
    one = client.get("/api/dashboard", params={"amount": 10, "days": 90, "banks": peers[0]}).json()
    assert one["banks"] == [peers[0]] and len(one["table"]) <= 3
    none = client.get("/api/dashboard", params={"amount": 10, "days": 90, "banks": "-"}).json()
    assert none["banks"] == [] and none["kpis"]["best_peer"] is None
    cur = client.get("/api/dashboard", params={"amount": 10, "days": 90, "statuses": ""}).json()
    assert cur["statuses"] == ["current"]


def test_bank_drilldown_and_report(client):
    name = client.get("/api/meta").json()["peers"][0]
    b = client.get("/api/bank", params={"name": name, "amount": 10}).json()
    assert b["curve"]["kind"] == "line" and b["rows"] and len(b["values"]) == len(b["rows"])
    assert client.get("/api/bank", params={"name": "nope"}).status_code == 404
    r = client.get("/api/report", params={"amount": 10})
    assert r.status_code == 200 and r.content[:2] == b"PK"           # xlsx is a zip


def test_chat_returns_chart_and_note(client):
    a = client.post("/api/chat", json={"question": "Compare Sberbank with other banks at 10 cr across tenors"}).json()
    assert a["chart"]["kind"] == "line" and a["note"] and a["grounded"]
    t = client.post("/api/chat", json={"question": "What is the best rate for 10 cr for 90 days?"}).json()
    assert not t["chart"] and t["text"]
    assert client.post("/api/chat", json={"question": "  "}).status_code == 422
    assert client.delete("/api/chat").json() == {"ok": True}


def test_operations_views(client):
    s = client.get("/api/ops/summary").json()
    assert s["manifest"]["rows"] > 1000 and s["sources_ok"] == s["sources_total"] and s["runs"]
    run = client.get(f"/api/ops/runs/{s['runs'][0]['run_id']}").json()
    assert run["status"] == "published" and run["sources"]
    assert client.get("/api/ops/runs/missing").status_code == 404
    assert client.post("/api/ops/runs/missing/approve").status_code == 409
    assert client.get("/api/ops/jobs/missing").status_code == 404
    assert client.get("/api/ops/evidence/missing/x.png").status_code == 404


def test_spa_is_served_and_unknown_paths_fall_back(client):
    from src.config import settings as S
    if (S.ROOT / "web" / "dist" / "index.html").exists():
        assert "<div id=\"root\">" in client.get("/").text
        assert "<div id=\"root\">" in client.get("/some/client/route").text
    assert client.get("/api/meta").headers["content-type"].startswith("application/json")
