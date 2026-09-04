from backend.telegram_digest import build_daily_analyst_message

_ANALYSIS = {
    "ok": True, "date": "2026-06-22", "qualityIsProxy": True,
    "rates": {"spend": 84.0, "leads": 142, "cpl": 0.59, "startRate": 71.0, "crmLeads": 12, "conversionLabel": "Lead rate"},
    "targets": {"maxCpl": 0.8},
    "audiences": [
        {"adsetId": "as1", "adsetName": "LAL-3%", "leads": 54, "cpl": 0.55, "quality": 78,
         "creatives": {"top": [{"adName": "vid_A", "cpl": 0.41, "holdRate": 0.48, "flags": []}],
                       "all": [{"adName": "vid_E", "flags": ["zero_result"]}]}},
    ],
    "recommendations": [
        {"action": "prioritize_audience", "target": "as1", "rationale": "LAL-3% highest quality.", "confidence": "high"},
    ],
}

def test_report_has_headline_rates_audiences_actions_and_proxy_note():
    msg = build_daily_analyst_message(_ANALYSIS)
    assert "Daily Funnel Analyst" in msg and "2026-06-22" in msg
    assert "$0.59" in msg and "71" in msg
    assert "LAL-3%" in msg and "78" in msg
    assert "prioritize" in msg.lower()
    assert "proxy" in msg.lower()

def test_report_handles_meta_failure():
    msg = build_daily_analyst_message({"ok": False, "error": "Meta not connected."})
    assert "could not" in msg.lower() or "not connected" in msg.lower()
