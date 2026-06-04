from backend.monitoring_rules import (
    COST_RULE_MIN_CLICKS,
    COST_RULE_MIN_SPEND,
    FREQUENCY_FATIGUE_THRESHOLD,
    evaluate_monitoring_snapshot,
)


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


def test_fallback_high_alert_fires_on_cpl_rise_and_lead_rate_drop_without_telegram():
    # No Telegram START data (the current reality) — the primary high rule can't fire,
    # but the fallback should catch the cheap-click-low-quality pattern.
    snapshot = {
        "campaignId": "cmp_fallback",
        "campaignName": "Income VSL",
        "current": {"spend": 200, "leads": 20, "telegramStarts": 0, "clicks": 400},
        "previous": {"spend": 100, "leads": 40, "telegramStarts": 0, "clicks": 200},
    }

    alerts = evaluate_monitoring_snapshot(snapshot)

    high = [a for a in alerts if a["severity"] == "high"]
    assert any("CPL rose while lead quality fell" in a["title"] for a in high)


def test_fallback_high_alert_suppressed_when_telegram_signal_present():
    # When Telegram START data exists, only the primary START-based rule should own the
    # high-severity quality alarm — the fallback must not double-fire.
    snapshot = {
        "campaignId": "cmp_with_tg",
        "campaignName": "Income VSL",
        "current": {"spend": 200, "leads": 20, "telegramStarts": 4, "clicks": 400},
        "previous": {"spend": 100, "leads": 40, "telegramStarts": 24, "clicks": 200},
    }

    alerts = evaluate_monitoring_snapshot(snapshot)

    assert not any("CPL rose while lead quality fell" in a["title"] for a in alerts)


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


def test_alerts_when_lead_rate_drops_while_spend_continues():
    snapshot = {
        "campaignId": "cmp_4",
        "campaignName": "New VSL Test",
        "current": {"spend": 120, "leads": 20, "telegramStarts": 10, "clicks": 500},
        "previous": {"spend": 100, "leads": 60, "telegramStarts": 35, "clicks": 450},
    }

    alerts = evaluate_monitoring_snapshot(snapshot)

    assert any("Lead rate dropped" in alert["title"] for alert in alerts)
    lead_rate_alert = next(alert for alert in alerts if "Lead rate dropped" in alert["title"])
    assert lead_rate_alert["severity"] == "medium"
    assert lead_rate_alert["whyItMatters"]
    assert len(lead_rate_alert["recommendedActions"]) == 3


def test_alerts_when_spend_and_clicks_exist_but_no_leads():
    snapshot = {
        "campaignId": "cmp_5",
        "campaignName": "Fresh Campaign",
        "current": {"spend": 80, "leads": 0, "telegramStarts": 0, "clicks": 260},
        "previous": {"spend": 60, "leads": 0, "telegramStarts": 0, "clicks": 180},
    }

    alerts = evaluate_monitoring_snapshot(snapshot)

    assert alerts[0]["severity"] == "high"
    assert "spend and clicks but no leads" in alerts[0]["title"]
    assert "landing page" in " ".join(alerts[0]["recommendedActions"]).lower()


def test_alerts_when_cpm_rises_sharply():
    snapshot = {
        "campaignId": "cmp_cpm",
        "campaignName": "Income VSL",
        "current": {"spend": 120, "leads": 30, "clicks": 200, "cpm": 14.0},
        "previous": {"spend": 80, "leads": 28, "clicks": 180, "cpm": 8.0},
    }

    alerts = evaluate_monitoring_snapshot(snapshot)

    assert any("CPM rose sharply" in alert["title"] for alert in alerts)
    cpm_alert = next(alert for alert in alerts if "CPM rose sharply" in alert["title"])
    assert cpm_alert["severity"] == "medium"


def test_alerts_on_cold_frequency_fatigue():
    snapshot = {
        "campaignId": "cmp_freq",
        "campaignName": "Cold Prospecting VSL",
        "current": {"spend": 120, "leads": 25, "clicks": 200, "frequency": 3.2},
        "previous": {"spend": 100, "leads": 24, "clicks": 190, "frequency": 1.9},
    }

    alerts = evaluate_monitoring_snapshot(snapshot)

    assert any("Frequency fatigue" in alert["title"] for alert in alerts)
    freq_alert = next(alert for alert in alerts if "Frequency fatigue" in alert["title"])
    assert freq_alert["metricDeltas"]["currentFrequency"] >= FREQUENCY_FATIGUE_THRESHOLD


def test_no_frequency_alert_when_frequency_field_missing():
    snapshot = {
        "campaignId": "cmp_nofreq",
        "campaignName": "Income VSL",
        "current": {"spend": 120, "leads": 25, "clicks": 200},
        "previous": {"spend": 100, "leads": 24, "clicks": 190},
    }

    alerts = evaluate_monitoring_snapshot(snapshot)

    assert not any("Frequency fatigue" in alert["title"] for alert in alerts)


def test_cost_rules_suppressed_below_volume_floor():
    # A thin, low-volume day with a big CPC jump must NOT trip the cost alarm.
    snapshot = {
        "campaignId": "cmp_thin",
        "campaignName": "Thin Day",
        "current": {"spend": COST_RULE_MIN_SPEND - 5, "leads": 1, "clicks": COST_RULE_MIN_CLICKS - 5, "cpm": 30, "frequency": 4.0},
        "previous": {"spend": 4, "leads": 1, "clicks": 30, "cpm": 8, "frequency": 1.0},
    }

    alerts = evaluate_monitoring_snapshot(snapshot)

    assert not any("CPC rose" in alert["title"] for alert in alerts)
    assert not any("CPM rose" in alert["title"] for alert in alerts)
    assert not any("Frequency fatigue" in alert["title"] for alert in alerts)


def test_tightened_cpc_trigger_fires_at_modest_rise():
    # +50% CPC rise (below the old +75% trigger) should now fire given enough volume.
    snapshot = {
        "campaignId": "cmp_cpc_modest",
        "campaignName": "Income VSL",
        "current": {"spend": 90, "leads": 20, "clicks": 100},   # cpc 0.90
        "previous": {"spend": 60, "leads": 20, "clicks": 100},  # cpc 0.60 -> +50%
    }

    alerts = evaluate_monitoring_snapshot(snapshot)

    assert any("CPC rose" in alert["title"] for alert in alerts)
