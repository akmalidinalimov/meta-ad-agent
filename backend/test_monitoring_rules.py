from backend.monitoring_rules import evaluate_monitoring_snapshot


def test_alerts_when_cpl_rises_and_start_rate_falls():
    snapshot = {
        "campaignId": "cmp_1",
        "campaignName": "Income VSL",
        "current": {"spend": 100, "leads": 20, "telegramStarts": 6, "clicks": 200},
        "previous": {"spend": 100, "leads": 40, "telegramStarts": 24, "clicks": 220},
    }

    alerts = evaluate_monitoring_snapshot(snapshot)

    assert alerts[0]["severity"] == "high"
    assert "CPL rose" in alerts[0]["title"]
    assert len(alerts[0]["recommendedActions"]) == 3


def test_alerts_when_cpc_rises_quickly():
    snapshot = {
        "campaignId": "cmp_2",
        "campaignName": "Business Automation VSL",
        "current": {"spend": 120, "leads": 30, "telegramStarts": 18, "clicks": 100},
        "previous": {"spend": 80, "leads": 28, "telegramStarts": 17, "clicks": 200},
    }

    alerts = evaluate_monitoring_snapshot(snapshot)

    assert alerts[0]["severity"] == "medium"
    assert "CPC rose" in alerts[0]["title"]


def test_no_alert_when_quality_is_stable():
    snapshot = {
        "campaignId": "cmp_1",
        "campaignName": "Income VSL",
        "current": {"spend": 100, "leads": 40, "telegramStarts": 22, "clicks": 210},
        "previous": {"spend": 100, "leads": 38, "telegramStarts": 20, "clicks": 205},
    }

    alerts = evaluate_monitoring_snapshot(snapshot)

    assert alerts == []


def test_alerts_when_leads_exist_but_telegram_start_tracking_is_missing():
    snapshot = {
        "campaignId": "cmp_3",
        "campaignName": "Creator VSL",
        "current": {"spend": 100, "leads": 60, "telegramStarts": 0, "clicks": 300},
        "previous": {"spend": 100, "leads": 55, "telegramStarts": 0, "clicks": 280},
    }

    alerts = evaluate_monitoring_snapshot(snapshot)

    assert alerts[0]["severity"] == "medium"
    assert "Telegram START tracking is missing" in alerts[0]["title"]
