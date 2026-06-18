"""Tests for the full KPI digest — it must mirror the web dashboard exactly (same
rate/cost math as src/components/simpleFunnel.ts) and degrade gracefully when a source
is unavailable."""

import backend.telegram_digest as telegram_digest
from backend.telegram_digest import (
    _cost,
    _rate,
    _sparkline,
    _trend_arrow,
    compose_kpi_digest_text,
    format_full_digest,
)


async def _no_history(campaign_id, days=7):
    return []

# Golden bundle: the SAME reference numbers as simpleFunnel.test.ts, in the live shapes
# returned by /api/campaigns/kpis, /api/crm/stages and /api/vsl.
KPIS = {
    "ok": True,
    "hasData": True,
    "kpis": {"spend": 321.22, "impressions": 120400, "reach": 88200},
    "rates": {"visitRate": 76.1, "leadRate": 72.5, "startRate": 50.7},
    "counts": {
        "linkClicks": 5080,
        "landingPageViews": 3865,
        "leads": 2801,
        "botStarts": 1420,
        "telegramLinkClicks": 2801,
        "subscribes": 0,
    },
    "startDenominatorSource": "telegram_link_click",
    "startScope": "account",
}
CRM = {
    "ok": True,
    "total": 178,
    "source": "AI Creators 5.0 buyurtmasi",
    "stages": [
        {"id": "NEW", "name": "New", "count": 120},
        {"id": "PAID", "name": "Paid", "count": 58},
    ],
}
VSL = {"ok": True, "configured": True, "views": 331, "viewsWatched50": None, "watchRate50": None, "hasRetention": False}


# --- pure math mirrors the dashboard ---------------------------------------------------


def test_rate_caps_at_100_and_is_zero_safe():
    assert _rate(3865, 5080) == 76.1
    assert _rate(9999, 50) == 100.0  # capped
    assert _rate(5, 0) == 0.0  # zero-safe


def test_cost_rounds_to_cents_and_is_zero_safe():
    assert _cost(321.22, 3865) == 0.08
    assert _cost(321.22, 178) == 1.8
    assert _cost(321.22, 0) == 0.0


# --- the full digest renders every dashboard section ----------------------------------


def test_full_digest_matches_the_dashboard_numbers():
    text = format_full_digest(KPIS, CRM, VSL)
    # Section headers
    assert "RATES" in text
    assert "COST PER STEP" in text
    assert "VOLUME" in text
    assert "CRM STAGES — AI Creators 5.0 buyurtmasi" in text
    assert "<pre>" in text  # monospace block for parse_mode=HTML
    # Rate cards (exactly the dashboard's five)
    assert "76.1%" in text  # visit
    assert "72.5%" in text  # lead
    assert "50.7%" in text  # start (backend select_start_rate)
    assert "23.3%" in text  # VSL view (331/1420)
    assert "12.5%" in text  # CRM fill (178/1420)
    # Cost per step
    assert "$0.08" in text  # per visit
    assert "$0.11" in text  # per lead
    assert "$0.23" in text  # per bot start
    assert "$0.97" in text  # per VSL view
    assert "$1.80" in text  # per CRM lead
    # Volume + CRM stages
    assert "$321.22" in text  # spend
    assert "120,400" in text  # impressions
    assert "1,420" in text  # bot starts
    # Start-rate denominator note uses Telegram button clicks
    assert "starts ÷ 2,801 button clicks" in text


def test_full_digest_account_wide_has_no_account_wide_flag():
    # Account-wide (no pinned campaign) must not tag the start row "· account-wide".
    text = format_full_digest(KPIS, CRM, VSL)
    assert "account-wide" in text  # subtitle scope
    assert "· account-wide" not in text  # but not on the start-rate row


def test_full_digest_pinned_campaign_flags_account_wide_starts():
    selection = {"campaignId": "c1", "campaignName": "DA - SHAHLOAI - VSL - 16.06.2026"}
    text = format_full_digest(KPIS, CRM, VSL, selection=selection)
    assert "campaign: DA - SHAHLOAI - VSL - 16.06.2026" in text
    assert "· account-wide" in text  # bot starts only attributable account-wide


def test_full_digest_targets_add_markers():
    text = format_full_digest(
        KPIS,
        CRM,
        VSL,
        targets={"maxCpl": 0.05, "minLeadRate": 80, "maxCostPerStart": None, "minStartRate": None},
    )
    assert "⚠️" in text  # per-lead $0.11 over its $0.05 ceiling, lead rate 72.5 under 80 floor


def test_full_digest_no_targets_no_markers():
    text = format_full_digest(KPIS, CRM, VSL)
    assert "✅" not in text
    assert "⚠️" not in text


def test_full_digest_vsl_unconfigured_prompts_connect():
    text = format_full_digest(KPIS, CRM, {"ok": False, "configured": False, "views": None})
    assert "connect YouTube to populate" in text


def test_full_digest_no_delivery_when_meta_ok_but_empty():
    text = format_full_digest({"ok": True, "hasData": False}, {"ok": False, "total": 0, "stages": []}, VSL)
    assert "no delivery in this window yet" in text


def test_full_digest_unavailable_when_meta_fetch_fails():
    text = format_full_digest({"ok": False}, {"ok": False, "total": 0, "stages": []}, VSL)
    assert "live data unavailable" in text


def test_full_digest_survives_empty_inputs():
    text = format_full_digest({}, {}, {})
    assert "KPI digest" in text
    assert "$0.00" in text


# --- compose wiring (patch the live fetch so we assert the wiring, not Meta) -----------


def test_compose_is_account_wide_when_no_campaign_pinned(monkeypatch):
    import backend.approval_store as approval_store
    import backend.kpi_digest_campaign_store as kpi_store
    import backend.targets_store as targets_store

    monkeypatch.setattr(kpi_store, "load_kpi_digest_campaign", lambda **kw: None)
    monkeypatch.setattr(targets_store, "load_targets", lambda **kw: {})
    monkeypatch.setattr(approval_store, "list_approval_requests", lambda **kw: [])

    async def _fake_gather(campaign_id, days):
        assert campaign_id is None  # account-wide
        return KPIS, CRM, VSL

    monkeypatch.setattr(telegram_digest, "_gather_digest_data", _fake_gather)
    monkeypatch.setattr(telegram_digest, "_gather_history", _no_history)

    text = compose_kpi_digest_text()
    assert "account-wide · live · last 90 days" in text
    assert "$321.22" in text


def test_compose_scopes_to_pinned_campaign(monkeypatch):
    import backend.approval_store as approval_store
    import backend.kpi_digest_campaign_store as kpi_store
    import backend.targets_store as targets_store

    selection = {"campaignId": "c1", "campaignName": "DA - SHAHLOAI - VSL - 16.06.2026"}
    monkeypatch.setattr(kpi_store, "load_kpi_digest_campaign", lambda **kw: selection)
    monkeypatch.setattr(targets_store, "load_targets", lambda **kw: {})
    monkeypatch.setattr(
        approval_store,
        "list_approval_requests",
        lambda **kw: [{"status": "needs_review"}, {"status": "needs_review"}],
    )

    async def _fake_gather(campaign_id, days):
        assert campaign_id == "c1"
        return KPIS, CRM, VSL

    monkeypatch.setattr(telegram_digest, "_gather_digest_data", _fake_gather)
    monkeypatch.setattr(telegram_digest, "_gather_history", _no_history)

    text = compose_kpi_digest_text()
    assert "campaign: DA - SHAHLOAI - VSL - 16.06.2026 · live · last 90 days" in text
    assert "2 suggestion(s) waiting" in text


# --- 7-day trend sparklines -----------------------------------------------------------


def test_sparkline_maps_levels_and_marks_gaps():
    assert _sparkline([0, 50, 100]) == "▁▅█"
    assert _sparkline([None]) == "·"
    assert _sparkline([]) == "—"


def test_trend_arrow_direction():
    assert _trend_arrow([10, 20]) == "↑"
    assert _trend_arrow([20, 10]) == "↓"
    assert _trend_arrow([10, 10]) == "→"
    assert _trend_arrow([10]) == ""  # need at least two points


def _history_point(date, *, link_clicks, landing, leads, starts, crm, vsl, start_rate):
    return {
        "date": date,
        "spend": 1.0,
        "startRate": start_rate,
        "counts": {
            "linkClicks": link_clicks,
            "landingViews": landing,
            "leads": leads,
            "botStarts": starts,
            "telegramLinkClicks": starts,
            "subscribes": 0,
            "crmLeads": crm,
            "vslViews": vsl,
        },
    }


def test_full_digest_renders_trend_section_with_history():
    history = [
        _history_point("2026-06-17", link_clicks=100, landing=50, leads=25, starts=10, crm=2, vsl=None, start_rate=40),
        _history_point("2026-06-18", link_clicks=100, landing=70, leads=35, starts=10, crm=3, vsl=None, start_rate=50),
        _history_point("2026-06-19", link_clicks=100, landing=90, leads=45, starts=10, crm=4, vsl=None, start_rate=60),
    ]
    text = format_full_digest(KPIS, CRM, VSL, history=history)
    assert "TREND (7d)" in text
    assert "↑" in text  # visit/lead/start all rising across the window
    assert "accruing" in text  # VSL has no daily data yet


def test_full_digest_without_history_has_no_trend_section():
    text = format_full_digest(KPIS, CRM, VSL)
    assert "TREND (7d)" not in text
