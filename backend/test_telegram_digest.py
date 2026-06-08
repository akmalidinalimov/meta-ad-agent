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
