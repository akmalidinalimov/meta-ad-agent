from backend.campaign_watch import build_campaign_watch


def test_campaign_watch_flags_clicks_with_no_leads_as_danger():
    dashboard = {
        "campaigns": [{"id": "cmp_1", "name": "Fresh VSL", "status": "active"}],
        "metrics": [
            {"date": "2026-05-30", "campaignId": "cmp_1", "spendUsd": 40, "clicks": 120, "leads": 0, "telegramSubscribers": 0},
            {"date": "2026-05-31", "campaignId": "cmp_1", "spendUsd": 80, "clicks": 260, "leads": 0, "telegramSubscribers": 0},
        ],
    }

    rows = build_campaign_watch(dashboard)

    assert rows[0]["tone"] == "danger"
    assert rows[0]["decision"] == "Fix tracking or landing page before scaling"
    assert rows[0]["cpc"] > 0


def test_campaign_watch_marks_stable_campaign_as_continue_monitoring():
    dashboard = {
        "campaigns": [{"id": "cmp_2", "name": "Stable VSL", "status": "active"}],
        "metrics": [
            {"date": "2026-05-30", "campaignId": "cmp_2", "spendUsd": 100, "clicks": 200, "leads": 30, "telegramSubscribers": 18},
            {"date": "2026-05-31", "campaignId": "cmp_2", "spendUsd": 110, "clicks": 210, "leads": 32, "telegramSubscribers": 19},
        ],
    }

    rows = build_campaign_watch(dashboard)

    assert rows[0]["tone"] == "good"
    assert rows[0]["decision"] == "Continue monitoring"
    assert rows[0]["leadRatePercent"] > 0


def test_campaign_watch_ignores_stale_campaigns_when_newer_metrics_exist():
    dashboard = {
        "campaigns": [
            {"id": "old", "name": "Old Campaign", "status": "paused"},
            {"id": "fresh", "name": "Fresh Campaign", "status": "active"},
        ],
        "metrics": [
            {"date": "2026-01-01", "campaignId": "old", "spendUsd": 100, "clicks": 200, "leads": 20, "telegramSubscribers": 0},
            {"date": "2026-01-02", "campaignId": "old", "spendUsd": 100, "clicks": 200, "leads": 20, "telegramSubscribers": 0},
            {"date": "2026-05-30", "campaignId": "fresh", "spendUsd": 100, "clicks": 200, "leads": 20, "telegramSubscribers": 10},
            {"date": "2026-05-31", "campaignId": "fresh", "spendUsd": 100, "clicks": 200, "leads": 20, "telegramSubscribers": 10},
        ],
    }

    rows = build_campaign_watch(dashboard)

    assert [row["campaignId"] for row in rows] == ["fresh"]
