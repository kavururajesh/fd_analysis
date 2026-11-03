from fastapi.testclient import TestClient

from src.api.routes import create_app


def test_health_and_validation():
    c = TestClient(create_app())
    h = c.get("/health").json()
    assert h["status"] == "ok" and "Rule-based" in h["llm"]
    assert c.get("/runs/doesnotexist").status_code == 404
    assert c.post("/runs/doesnotexist/approve").status_code == 409
    assert c.get("/rates").status_code == 422
