import asyncio

from backend.bitrix_client import (
    BitrixConfig,
    build_bitrix_webhook_url,
    fetch_bitrix_leads,
    fetch_bitrix_statuses,
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
