from fastapi.testclient import TestClient

import backend.app as app_module
from backend.app import app
from backend.monitoring_runner import list_monitoring_alerts, run_monitoring_check
from backend.monitoring_scheduler import list_monitoring_runs, run_scheduled_monitoring


def sample_monitoring_dashboard() -> dict:
    return {
        "campaigns": [
            {"id": "cmp_1", "name": "Income VSL"},
            {"id": "cmp_2", "name": "Stable VSL"},
        ],
        "metrics": [
            {"date": "2026-05-01", "campaignId": "cmp_1", "spendUsd": 100, "clicks": 220, "leads": 40, "telegramSubscribers": 24},
            {"date": "2026-05-02", "campaignId": "cmp_1", "spendUsd": 100, "clicks": 200, "leads": 20, "telegramSubscribers": 6},
            {"date": "2026-05-01", "campaignId": "cmp_2", "spendUsd": 100, "clicks": 205, "leads": 38, "telegramSubscribers": 20},
            {"date": "2026-05-02", "campaignId": "cmp_2", "spendUsd": 100, "clicks": 210, "leads": 40, "telegramSubscribers": 22},
        ],
    }


def bind_tmp_monitoring(monkeypatch, tmp_path):
    storage_dir = tmp_path / "storage"
    monkeypatch.setattr(app_module, "dashboard", sample_monitoring_dashboard)
    monkeypatch.setattr(
        app_module,
        "run_monitoring_check",
        lambda dashboard_data, send_alert: run_monitoring_check(
            dashboard_data,
            storage_dir=storage_dir,
            send_alert=send_alert,
        ),
    )
    monkeypatch.setattr(
        app_module,
        "list_monitoring_alerts",
        lambda: list_monitoring_alerts(storage_dir=storage_dir),
    )
    return storage_dir


def test_manual_monitoring_run_stores_alert_and_sends_telegram(monkeypatch, tmp_path):
    bind_tmp_monitoring(monkeypatch, tmp_path)
    sent = []
    monkeypatch.setattr(app_module, "send_telegram_message_sync", lambda text: sent.append(text) or {"ok": True})
    client = TestClient(app)

    response = client.post("/api/monitoring/run")

    payload = response.json()
    stored = client.get("/api/monitoring/alerts").json()["alerts"]

    assert response.status_code == 200
    assert payload["ok"] is True
    assert len(payload["alerts"]) == 1
    assert payload["alerts"][0]["severity"] == "high"
    assert stored[0]["title"] == payload["alerts"][0]["title"]
    assert "CPL rose" in sent[0]


def test_monitoring_alerts_endpoint_returns_empty_list_before_run(monkeypatch, tmp_path):
    bind_tmp_monitoring(monkeypatch, tmp_path)
    client = TestClient(app)

    response = client.get("/api/monitoring/alerts")

    assert response.status_code == 200
    assert response.json()["alerts"] == []


def test_monitoring_ignores_completed_old_campaigns(tmp_path):
    dashboard = {
        "campaigns": [
            {"id": "old_cmp", "name": "Old completed", "status": "completed"},
            {"id": "active_cmp", "name": "Active", "status": "active"},
        ],
        "metrics": [
            {"date": "2026-01-01", "campaignId": "old_cmp", "spendUsd": 10, "clicks": 100, "leads": 20, "telegramSubscribers": 10},
            {"date": "2026-01-02", "campaignId": "old_cmp", "spendUsd": 50, "clicks": 10, "leads": 1, "telegramSubscribers": 0},
            {"date": "2026-05-29", "campaignId": "active_cmp", "spendUsd": 100, "clicks": 200, "leads": 40, "telegramSubscribers": 20},
            {"date": "2026-05-30", "campaignId": "active_cmp", "spendUsd": 100, "clicks": 205, "leads": 39, "telegramSubscribers": 20},
        ],
    }

    result = run_monitoring_check(dashboard, storage_dir=tmp_path / "storage")

    assert result["snapshotsChecked"] == 1
    assert result["alerts"] == []


def test_monitoring_ignores_stale_active_campaigns_outside_latest_window(tmp_path):
    dashboard = {
        "campaigns": [
            {"id": "stale_cmp", "name": "Old but paused", "status": "paused"},
            {"id": "fresh_cmp", "name": "Fresh campaign", "status": "active"},
        ],
        "metrics": [
            {"date": "2026-01-01", "campaignId": "stale_cmp", "spendUsd": 100, "clicks": 300, "leads": 60, "telegramSubscribers": 0},
            {"date": "2026-01-02", "campaignId": "stale_cmp", "spendUsd": 100, "clicks": 280, "leads": 55, "telegramSubscribers": 0},
            {"date": "2026-05-04", "campaignId": "fresh_cmp", "spendUsd": 100, "clicks": 200, "leads": 40, "telegramSubscribers": 20},
            {"date": "2026-05-05", "campaignId": "fresh_cmp", "spendUsd": 100, "clicks": 205, "leads": 39, "telegramSubscribers": 20},
        ],
    }

    result = run_monitoring_check(dashboard, storage_dir=tmp_path / "storage")

    assert result["snapshotsChecked"] == 1
    assert result["alerts"] == []


def test_scheduled_monitoring_runs_once_per_interval_and_logs_results(tmp_path):
    storage_dir = tmp_path / "storage"
    sent = []

    first = run_scheduled_monitoring(
        sample_monitoring_dashboard,
        storage_dir=storage_dir,
        send_alert=lambda text: sent.append(text) or {"ok": True},
    )
    second = run_scheduled_monitoring(
        sample_monitoring_dashboard,
        storage_dir=storage_dir,
        send_alert=lambda text: sent.append(text) or {"ok": True},
    )

    runs = list_monitoring_runs(storage_dir=storage_dir)
    assert first["ok"] is True
    assert first["skipped"] is False
    assert second["ok"] is True
    assert second["skipped"] is True
    assert len(runs) == 2
    assert runs[0]["status"] == "skipped"
    assert runs[1]["status"] == "completed"


def test_scheduled_monitoring_endpoint_exposes_safe_run_log(monkeypatch, tmp_path):
    storage_dir = tmp_path / "storage"
    monkeypatch.setattr(app_module, "dashboard", sample_monitoring_dashboard)
    monkeypatch.setattr(
        app_module,
        "run_scheduled_monitoring",
        lambda dashboard_factory, send_alert, force=False: run_scheduled_monitoring(
            dashboard_factory,
            storage_dir=storage_dir,
            send_alert=send_alert,
            force=force,
        ),
    )
    monkeypatch.setattr(app_module, "list_monitoring_runs", lambda: list_monitoring_runs(storage_dir=storage_dir))
    monkeypatch.setattr(app_module, "send_telegram_message_sync", lambda text: {"ok": True})
    client = TestClient(app)

    run_response = client.post("/api/monitoring/scheduled", json={"force": True})
    status_response = client.get("/api/monitoring/runs")

    assert run_response.status_code == 200
    assert run_response.json()["mode"] == "alert_only"
    assert status_response.status_code == 200
    assert status_response.json()["runs"][0]["status"] == "completed"
