"""CRM lead-cost on /api/crm/stages: account Meta spend ÷ CRM leads (and ÷ paid = cost/sale).
Bitrix + Meta are mocked, so this asserts the cost math + that it respects the window, not
the network calls."""

from datetime import date
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
