from datetime import date

from backend.meta_sync import build_sync_windows


def test_build_sync_windows_creates_inclusive_90_day_chunks():
    windows = build_sync_windows(days=90, end_date=date(2026, 5, 28), chunk_days=7)

    assert windows[0] == (date(2026, 2, 28), date(2026, 3, 6))
    assert windows[-1] == (date(2026, 5, 23), date(2026, 5, 28))
    assert len(windows) == 13


def test_build_sync_windows_supports_six_month_imports():
    windows = build_sync_windows(days=180, end_date=date(2026, 5, 28), chunk_days=7)

    assert windows[0] == (date(2025, 11, 30), date(2025, 12, 6))
    assert windows[-1] == (date(2026, 5, 24), date(2026, 5, 28))
    assert len(windows) == 26
