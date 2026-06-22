from datetime import datetime
from zoneinfo import ZoneInfo
from backend.daily_analysis_scheduler import should_run_daily

STK = ZoneInfo("Europe/Stockholm")

def test_fires_at_or_after_18_when_not_run_today():
    assert should_run_daily(datetime(2026, 6, 22, 18, 5, tzinfo=STK), last_run_date=None) is True

def test_does_not_fire_before_18():
    assert should_run_daily(datetime(2026, 6, 22, 17, 59, tzinfo=STK), last_run_date=None) is False

def test_does_not_fire_twice_same_day():
    assert should_run_daily(datetime(2026, 6, 22, 18, 30, tzinfo=STK), last_run_date="2026-06-22") is False
