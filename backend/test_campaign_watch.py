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


def test_campaign_watch_flags_under_delivery_pacing():
    dashboard = {
        "campaigns": [{"id": "cmp_pace", "name": "Under Pacing", "status": "active", "dailyBudgetUsd": 100}],
        "metrics": [
            {"date": "2026-05-30", "campaignId": "cmp_pace", "spendUsd": 40, "clicks": 200, "leads": 30, "telegramSubscribers": 12},
            {"date": "2026-05-31", "campaignId": "cmp_pace", "spendUsd": 45, "clicks": 210, "leads": 32, "telegramSubscribers": 13},
        ],
    }

    rows = build_campaign_watch(dashboard)

    assert rows[0]["pacing"]["status"] == "under_delivering"
    assert rows[0]["pacing"]["utilizationPercent"] < 70
    assert rows[0]["dailyBudgetUsd"] == 100


def test_campaign_watch_pacing_unknown_without_budget():
    dashboard = {
        "campaigns": [{"id": "cmp_nb", "name": "No Budget", "status": "active"}],
        "metrics": [
            {"date": "2026-05-30", "campaignId": "cmp_nb", "spendUsd": 60, "clicks": 200, "leads": 30, "telegramSubscribers": 12},
            {"date": "2026-05-31", "campaignId": "cmp_nb", "spendUsd": 60, "clicks": 210, "leads": 32, "telegramSubscribers": 13},
        ],
    }

    rows = build_campaign_watch(dashboard)

    assert rows[0]["pacing"]["status"] == "unknown"


def test_in_learning_campaign_is_not_recommended_for_scaling():
    # Healthy lead flow but rolling conversions below the learning exit target.
    dashboard = {
        "campaigns": [{"id": "cmp_learn", "name": "Learning VSL", "status": "active", "dailyBudgetUsd": 100}],
        "metrics": [
            {"date": "2026-05-30", "campaignId": "cmp_learn", "spendUsd": 90, "clicks": 200, "leads": 12, "telegramSubscribers": 8},
            {"date": "2026-05-31", "campaignId": "cmp_learn", "spendUsd": 95, "clicks": 210, "leads": 13, "telegramSubscribers": 9},
        ],
    }

    rows = build_campaign_watch(dashboard)
    row = rows[0]

    assert row["learning"]["phase"] == "learning"
    assert row["decision"] == "Let learning finish before scaling"
    joined = " ".join(row["nextActions"]).lower()
    assert "scale" not in joined or "do not scale" in joined
    assert all("20% scale proposal" not in action for action in row["nextActions"])


def test_past_learning_campaign_can_be_recommended_for_scaling():
    dashboard = {
        "campaigns": [{"id": "cmp_active", "name": "Mature VSL", "status": "active", "dailyBudgetUsd": 100}],
        "metrics": [
            {"date": "2026-05-30", "campaignId": "cmp_active", "spendUsd": 90, "clicks": 400, "leads": 60, "telegramSubscribers": 35},
            {"date": "2026-05-31", "campaignId": "cmp_active", "spendUsd": 95, "clicks": 410, "leads": 62, "telegramSubscribers": 36},
        ],
    }

    rows = build_campaign_watch(dashboard)
    row = rows[0]

    assert row["learning"]["phase"] == "active"
    assert row["decision"] == "Continue monitoring"
