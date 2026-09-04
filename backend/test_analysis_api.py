from fastapi.testclient import TestClient
import backend.routers.analysis as analysis_router
from backend.app import app


def test_post_daily_forces_run(monkeypatch):
    monkeypatch.setattr(analysis_router, "run_scheduled_daily_analysis",
                        lambda **kw: {"skipped": False, "ok": True, "sent": True})
    body = TestClient(app).post("/api/analysis/daily").json()
    assert body["ok"] is True and body["sent"] is True


def test_get_daily_returns_analysis(monkeypatch):
    async def fake_run():
        return {"ok": True, "audiences": [], "recommendations": [], "rates": {}}
    monkeypatch.setattr(analysis_router, "run_daily_analysis", fake_run)
    body = TestClient(app).get("/api/analysis/daily").json()
    assert body["ok"] is True and "recommendations" in body
