import asyncio

from backend.bitrix_client import (
    BitrixConfig,
    build_bitrix_webhook_url,
    fetch_bitrix_deals,
    fetch_bitrix_leads,
    fetch_bitrix_statuses,
    normalize_bitrix_deal,
    normalize_bitrix_lead,
    normalize_bitrix_status,
)


class FakeBitrixTransport:
    def __init__(self):
        self.calls = []

    async def call(self, method, params):
        self.calls.append((method, params))
        if method == "crm.status.list":
            return {
                "result": [
                    {"ID": "1", "ENTITY_ID": "STATUS", "STATUS_ID": "NEW", "NAME": "New lead", "SORT": "10"},
                    {"ID": "2", "ENTITY_ID": "STATUS", "STATUS_ID": "CONVERTED", "NAME": "Converted", "SORT": "20"},
                ]
            }
        return {
            "result": [
                {
                    "ID": "101",
                    "TITLE": "AI course lead",
                    "STATUS_ID": "NEW",
                    "SOURCE_ID": "Instagram",
                    "PHONE": [{"VALUE": "+998901234567"}],
                    "UTM_CAMPAIGN": "cmp_income",
                    "UF_CRM_VISITOR_ID": "v_abc123",
                }
            ]
        }


def test_build_bitrix_webhook_url_from_full_url():
    config = BitrixConfig(webhook_url="https://example.bitrix24.com/rest/1/secret/", portal_url="", user_id="", webhook_key="")

    assert build_bitrix_webhook_url(config) == "https://example.bitrix24.com/rest/1/secret/"


def test_build_bitrix_webhook_url_from_parts():
    config = BitrixConfig(webhook_url="", portal_url="https://example.bitrix24.com", user_id="1", webhook_key="secret")

    assert build_bitrix_webhook_url(config) == "https://example.bitrix24.com/rest/1/secret/"


def test_normalize_bitrix_lead_maps_attribution_and_stage():
    normalized = normalize_bitrix_lead(
        {
            "ID": "101",
            "TITLE": "AI course lead",
            "STATUS_ID": "IN_PROCESS",
            "PHONE": [{"VALUE": "+998901234567"}],
            "UTM_CAMPAIGN": "cmp_income",
            "UTM_CONTENT": "creative_7",
            "UF_CRM_VISITOR_ID": "v_abc123",
            "UF_CRM_TELEGRAM_USER_ID": "tg_77",
        }
    )

    assert normalized["crmLeadId"] == "101"
    assert normalized["stage"] == "IN_PROCESS"
    assert normalized["visitorId"] == "v_abc123"
    assert normalized["telegramUserId"] == "tg_77"
    assert normalized["utmCampaign"] == "cmp_income"


def test_fetch_bitrix_leads_uses_crm_lead_list():
    transport = FakeBitrixTransport()

    leads = asyncio.run(fetch_bitrix_leads(transport=transport, limit=50))

    assert transport.calls == [("crm.lead.list", {"order": {"DATE_CREATE": "DESC"}, "select": ["*", "UF_*"], "start": 0})]
    assert leads[0]["crmLeadId"] == "101"


def test_normalize_bitrix_status_keeps_stage_identity_and_label():
    normalized = normalize_bitrix_status(
        {"ID": "2", "ENTITY_ID": "STATUS", "STATUS_ID": "CONVERTED", "NAME": "Converted", "SORT": "20"}
    )

    assert normalized == {
        "id": "2",
        "entityId": "STATUS",
        "statusId": "CONVERTED",
        "name": "Converted",
        "sort": 20,
    }


def test_fetch_bitrix_statuses_uses_crm_status_list_for_lead_stages():
    transport = FakeBitrixTransport()

    statuses = asyncio.run(fetch_bitrix_statuses(transport=transport, entity_id="STATUS"))

    assert transport.calls == [
        ("crm.status.list", {"filter": {"ENTITY_ID": "STATUS"}, "order": {"SORT": "ASC"}})
    ]
    assert [status["statusId"] for status in statuses] == ["NEW", "CONVERTED"]


class PagingBitrixTransport:
    def __init__(self):
        self.calls = []

    async def call(self, method, params):
        self.calls.append((method, params))
        start = params.get("start", 0)
        if start == 0:
            return {"result": [{"ID": "1", "STATUS_ID": "NEW", "STAGE_ID": "C1:NEW"}], "next": 50}
        return {"result": [{"ID": "2", "STATUS_ID": "NEW", "STAGE_ID": "C1:NEW"}]}


def test_fetch_bitrix_leads_follows_next_paging():
    transport = PagingBitrixTransport()

    leads = asyncio.run(fetch_bitrix_leads(transport=transport, limit=None))

    assert [call[1]["start"] for call in transport.calls] == [0, 50]
    assert [lead["crmLeadId"] for lead in leads] == ["1", "2"]


def test_fetch_bitrix_leads_adds_date_filter_when_days_given():
    transport = PagingBitrixTransport()

    asyncio.run(fetch_bitrix_leads(transport=transport, days=7, limit=None))

    first_params = transport.calls[0][1]
    assert ">=DATE_CREATE" in first_params["filter"]


def test_normalize_bitrix_deal_reads_stage_id_and_utm():
    out = normalize_bitrix_deal(
        {"ID": "5", "STAGE_ID": "C1:WON", "PHONE": [{"VALUE": "+998901112233"}], "UTM_CONTENT": "ai"}
    )

    assert out["crmLeadId"] == "5"
    assert out["stage"] == "C1:WON"
    assert out["phone"] == "+998901112233"
    assert out["utmContent"] == "ai"


def test_fetch_bitrix_leads_filters_by_title():
    transport = PagingBitrixTransport()

    asyncio.run(fetch_bitrix_leads(transport=transport, title_contains="AI Creators 5.0 buyurtmasi", limit=None))

    assert transport.calls[0][1]["filter"]["%TITLE"] == "AI Creators 5.0 buyurtmasi"


def test_fetch_bitrix_deals_uses_crm_deal_list():
    transport = PagingBitrixTransport()

    deals = asyncio.run(fetch_bitrix_deals(transport=transport, limit=None))

    assert transport.calls[0][0] == "crm.deal.list"
    assert deals[0]["crmLeadId"] == "1"
    assert deals[0]["stage"] == "C1:NEW"
