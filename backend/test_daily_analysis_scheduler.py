from datetime import datetime
from zoneinfo import ZoneInfo
from backend.daily_analysis_scheduler import should_run_daily
import backend.daily_analysis_scheduler as sched

STK = ZoneInfo("Europe/Stockholm")

def test_fires_at_or_after_18_when_not_run_today():
    assert should_run_daily(datetime(2026, 6, 22, 18, 5, tzinfo=STK), last_run_date=None) is True

def test_does_not_fire_before_18():
    assert should_run_daily(datetime(2026, 6, 22, 17, 59, tzinfo=STK), last_run_date=None) is False

def test_does_not_fire_twice_same_day():
    assert should_run_daily(datetime(2026, 6, 22, 18, 30, tzinfo=STK), last_run_date="2026-06-22") is False


def test_run_scheduled_daily_analysis_writes_runlog_and_sends(monkeypatch, tmp_path):
    async def fake_run():
        return {
            "ok": True,
            "rates": {"spend": 10.0, "leads": 5, "cpl": 2.0, "startRate": 50.0, "crmLeads": 3, "conversionLabel": "Leads"},
            "audiences": [],
            "recommendations": [],
            "targets": {},
            "date": "2026-06-22",
            "qualityIsProxy": True,
        }
    monkeypatch.setattr("backend.daily_analyst.run_daily_analysis", fake_run)
    monkeypatch.setattr("backend.telegram_outbound.send_telegram_message_sync", lambda *a, **k: {"ok": True})
    out = sched.run_scheduled_daily_analysis(force=True, storage_dir=tmp_path)
    assert out == {"skipped": False, "ok": True, "sent": True}
    assert (tmp_path / sched.RUN_FILE).exists()


def test_run_intraday_anomaly_check_debounces_same_day(monkeypatch, tmp_path):
    async def fake_alerts():
        return [{"kind": "cpl_spike", "message": "spike"}]
    monkeypatch.setattr("backend.daily_analyst.intraday_anomaly_alerts", fake_alerts)
    sent = []
    monkeypatch.setattr("backend.telegram_outbound.send_telegram_message_sync", lambda msg, *a, **k: sent.append(msg))
    first = sched.run_intraday_anomaly_check(storage_dir=tmp_path)
    second = sched.run_intraday_anomaly_check(storage_dir=tmp_path)
    assert first["new"] == 1 and second["new"] == 0      # debounced: same kind not re-sent same day
    assert len(sent) == 1
