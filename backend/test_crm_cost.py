"""CRM lead-cost on /api/crm/stages: account Meta spend ÷ CRM leads (and ÷ paid = cost/sale).
Bitrix + Meta are mocked, so this asserts the cost math + that it respects the window, not
the network calls."""

from datetime import date, timedelta
from types import SimpleNamespace

from fastapi.testclient import TestClient

import backend.routers.crm as crm_router
from backend.app import app


def _cfg_ok():
    return SimpleNamespace(is_configured=True)


def test_crm_stages_exposes_cost_per_lead_and_sale(monkeypatch):
    today = date.today().isoformat()
    monkeypatch.setattr(crm_router, "get_bitrix_config", _cfg_ok)
    monkeypatch.setattr(crm_router, "build_bitrix_transport", lambda config: None)

    async def fake_leads(*, transport, days=30, limit=None, title_contains=None):
        # 4 leads created today; one is paid (CONVERTED).
        return [
            {"crmLeadId": "1", "stage": "NEW", "createdAt": today + "T10:00:00", "sourceDescription": "", "utmContent": ""},
            {"crmLeadId": "2", "stage": "NEW", "createdAt": today + "T11:00:00", "sourceDescription": "", "utmContent": ""},
            {"crmLeadId": "3", "stage": "NEW", "createdAt": today + "T12:00:00", "sourceDescription": "", "utmContent": ""},
            {"crmLeadId": "4", "stage": "CONVERTED", "createdAt": today + "T13:00:00", "sourceDescription": "", "utmContent": ""},
        ]

    async def fake_statuses(*, transport, entity_id="STATUS"):
        return [{"statusId": "NEW", "name": "New"}, {"statusId": "CONVERTED", "name": "Converted"}]

    async def fake_spend(since_iso, until_iso):
        assert since_iso == today and until_iso == today   # spend scoped to the same window
        return 80.0

    monkeypatch.setattr(crm_router, "fetch_bitrix_leads", fake_leads)
    monkeypatch.setattr(crm_router, "fetch_bitrix_statuses", fake_statuses)
    monkeypatch.setattr(crm_router, "_account_spend", fake_spend)
    monkeypatch.setenv("BITRIX_PAID_STATUS_IDS", "CONVERTED")

    body = TestClient(app).get(f"/api/crm/stages?since={today}&until={today}&force=true").json()
    assert body["ok"] is True
    assert body["spend"] == 80.0
    assert body["leadsAll"] == 4
    assert body["paidAll"] == 1
    assert body["costPerLead"] == 20.0     # 80 / 4 leads
    assert body["costPerSale"] == 80.0     # 80 / 1 paid


def test_crm_stages_cost_is_none_when_no_leads(monkeypatch):
    today = date.today().isoformat()
    monkeypatch.setattr(crm_router, "get_bitrix_config", _cfg_ok)
    monkeypatch.setattr(crm_router, "build_bitrix_transport", lambda config: None)

    async def no_leads(*, transport, days=30, limit=None, title_contains=None):
        return []

    async def fake_statuses(*, transport, entity_id="STATUS"):
        return [{"statusId": "NEW", "name": "New"}]

    async def fake_spend(since_iso, until_iso):
        return 50.0

    monkeypatch.setattr(crm_router, "fetch_bitrix_leads", no_leads)
    monkeypatch.setattr(crm_router, "fetch_bitrix_statuses", fake_statuses)
    monkeypatch.setattr(crm_router, "_account_spend", fake_spend)

    body = TestClient(app).get(f"/api/crm/stages?since={today}&until={today}&force=true").json()
    assert body["leadsAll"] == 0
    assert body["costPerLead"] is None     # no division by zero
    assert body["costPerSale"] is None


def test_crm_stages_buckets_leads_on_tashkent_day(monkeypatch):
    """A lead created 22:30 at +03:00 (Bitrix/Moscow) is 00:30 Tashkent the NEXT day, so it must
    count toward the Tashkent 'today' window — not the previous day. This was the bug that dropped
    late-night leads and inflated cost-per-lead."""
    today = date.today()
    yest = (today - timedelta(days=1)).isoformat()
    todays = today.isoformat()
    monkeypatch.setattr(crm_router, "get_bitrix_config", _cfg_ok)
    monkeypatch.setattr(crm_router, "build_bitrix_transport", lambda config: None)

    async def fake_leads(*, transport, days=30, limit=None, title_contains=None):
        return [
            # 22:30 +03:00 yesterday == 00:30 Tashkent today -> belongs to TODAY (old code dropped it)
            {"crmLeadId": "1", "stage": "NEW", "createdAt": f"{yest}T22:30:00+03:00", "sourceDescription": "", "utmContent": ""},
            {"crmLeadId": "2", "stage": "NEW", "createdAt": f"{todays}T14:00:00+03:00", "sourceDescription": "", "utmContent": ""},
        ]

    async def fake_statuses(*, transport, entity_id="STATUS"):
        return [{"statusId": "NEW", "name": "New"}]

    async def fake_spend(since_iso, until_iso):
        return 60.0

    monkeypatch.setattr(crm_router, "fetch_bitrix_leads", fake_leads)
    monkeypatch.setattr(crm_router, "fetch_bitrix_statuses", fake_statuses)
    monkeypatch.setattr(crm_router, "_account_spend", fake_spend)

    body = TestClient(app).get(f"/api/crm/stages?since={todays}&until={todays}&force=true").json()
    assert body["leadsAll"] == 2          # both leads are Tashkent-today
    assert body["costPerLead"] == 30.0    # 60 / 2 (not 60 / 1 = 60 if the late-night lead were dropped)


def test_lead_day_converts_bitrix_offset_to_tashkent():
    assert crm_router._lead_day("2026-06-28T23:30:00+03:00") == "2026-06-29"  # 01:30 Tashkent next day
    assert crm_router._lead_day("2026-06-29T00:30:00+03:00") == "2026-06-29"  # 02:30 Tashkent same day
    assert crm_router._lead_day("2026-06-29T20:30:00") == "2026-06-30"        # naive treated as UTC -> 01:30 next day Tashkent
    assert crm_router._lead_day("2026-13-99garbage") == "2026-13-99"          # unparseable -> first 10 chars
