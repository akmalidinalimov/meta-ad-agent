from backend.telegram_digest import build_kpi_rows, format_kpi_digest


SUMMARY = {
    "spend": 3487.87,
    "leads": 44082,
    "cpl": 0.06,
    "cpp": 0,
    "ctr": 2.26,
    "leadRateFromClick": 45.4,
    "purchases": 0,
}
FUNNEL = {
    "uniqueTelegramUsers": 128,
    "rates": {"telegramStartRate": 8.1},
}


def test_build_kpi_rows_has_seven_core_kpis():
    rows = build_kpi_rows(SUMMARY, FUNNEL)
    labels = [label for label, _ in rows]
    assert labels == [
        "Spend (90d)",
        "Leads",
        "Lead rate",
        "CTR",
        "Telegram STARTs",
        "START rate",
        "Purchases",
    ]


def test_format_kpi_digest_includes_values_and_cost_per_start():
    text = format_kpi_digest(SUMMARY, FUNNEL, pending_approvals=2, subtitle="last 90 days")
    assert "KPI digest" in text
    assert "$3,487.87" in text          # spend
    assert "44,082" in text             # leads
    assert "$0.06" in text              # CPL
    assert "45.40%" in text             # lead rate
    assert "2.26%" in text              # CTR
    assert "128" in text                # telegram starts
    assert "/start)" in text            # cost per start computed
    assert "8.10%" in text              # start rate
    assert "tracking gap" in text       # zero purchases labelled
    assert "2 suggestion(s) waiting" in text
    assert "<pre>" in text              # HTML table block for parse_mode=HTML


def test_format_kpi_digest_handles_no_telegram_events():
    text = format_kpi_digest(SUMMARY, {"uniqueTelegramUsers": 0, "rates": {}})
    assert "no events yet" in text


def test_format_kpi_digest_survives_empty_inputs():
    text = format_kpi_digest({}, {})
    assert "KPI digest" in text
    assert "$0.00" in text


def test_targets_add_pass_and_breach_markers():
    # CPL 0.06 <= maxCpl 0.10 -> pass; lead rate 45.42 < minLeadRate 60 -> breach.
    text = format_kpi_digest(
        SUMMARY,
        FUNNEL,
        targets={"maxCpl": 0.10, "minLeadRate": 60, "maxCostPerStart": None, "minStartRate": None},
    )
    assert "✅" in text   # CPL under its ceiling
    assert "⚠️" in text   # lead rate under its floor


def test_no_targets_means_no_markers():
    text = format_kpi_digest(SUMMARY, FUNNEL)
    assert "✅" not in text
    assert "⚠️" not in text


# --- Per-campaign digest scoping (KPI campaign picker) -----------------------

from backend.telegram_digest import _campaign_funnel, _campaign_summary, compose_kpi_digest_text


def _knowledge_with_two_campaigns():
    return {
        "raw": {
            "insights": {
                "base": [
                    {
                        "campaign_id": "c1",
                        "campaign_name": "Alpha",
                        "spend": "100",
                        "impressions": "1000",
                        "clicks": "100",
                        "actions": [
                            {"action_type": "lead", "value": "20"},
                            {"action_type": "subscribe", "value": "8"},
                        ],
                    },
                    {
                        "campaign_id": "c2",
                        "campaign_name": "Beta",
                        "spend": "50",
                        "impressions": "500",
                        "clicks": "50",
                        "actions": [{"action_type": "lead", "value": "5"}],
                    },
                ]
            }
        },
        "analysis": {"summary": {"spend": 150, "leads": 25, "cpl": 6, "ctr": 1, "purchases": 0}},
        "snapshot": {"generatedAt": "2026-06-17T00:00:00Z"},
    }


def test_campaign_summary_scopes_to_one_campaign():
    summary, name = _campaign_summary(_knowledge_with_two_campaigns(), "c1")
    assert name == "Alpha"
    assert summary["spend"] == 100  # only c1's spend, not the 150 account total
    assert summary["leads"] == 20
    assert summary["subscribes"] == 8


def test_campaign_summary_is_none_for_unknown_campaign():
    assert _campaign_summary(_knowledge_with_two_campaigns(), "missing") is None


def test_campaign_funnel_uses_subscribes_over_leads_and_caps():
    funnel = _campaign_funnel({"subscribes": 8, "leads": 20})
    assert funnel["uniqueTelegramUsers"] == 8
    assert funnel["rates"]["telegramStartRate"] == 40.0  # 8 / 20
    assert _campaign_funnel({"subscribes": 30, "leads": 10})["rates"]["telegramStartRate"] == 100.0


def _patch_digest_sources(monkeypatch, *, selection):
    import backend.approval_store as approval_store
    import backend.funnel_events as funnel_events
    import backend.knowledge_base as kb
    import backend.kpi_digest_campaign_store as kpi_store
    import backend.targets_store as targets_store

    monkeypatch.setattr(kb, "load_knowledge_base", lambda: _knowledge_with_two_campaigns())
    monkeypatch.setattr(kpi_store, "load_kpi_digest_campaign", lambda **kw: selection)
    monkeypatch.setattr(funnel_events, "build_funnel_summary", lambda **kw: {"uniqueTelegramUsers": 999, "rates": {"telegramStartRate": 99}})
    monkeypatch.setattr(targets_store, "load_targets", lambda **kw: {})
    monkeypatch.setattr(approval_store, "list_approval_requests", lambda **kw: [])


def test_compose_is_account_wide_when_no_campaign_pinned(monkeypatch):
    _patch_digest_sources(monkeypatch, selection=None)
    text = compose_kpi_digest_text()
    assert "account-wide" in text
    assert "$150.00" in text  # account-total spend, account funnel STARTs (999)
    assert "999" in text


def test_compose_scopes_to_pinned_campaign(monkeypatch):
    _patch_digest_sources(monkeypatch, selection={"campaignId": "c1", "campaignName": "Alpha"})
    text = compose_kpi_digest_text()
    assert "campaign: Alpha" in text
    assert "$100.00" in text  # c1's spend
    assert "$150.00" not in text  # not the account total
    # Scoped digest uses Meta per-campaign subscribes (8), not the account funnel's 999.
    assert "999" not in text
