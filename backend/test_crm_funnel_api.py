from fastapi.testclient import TestClient

import backend.app as app_module
from backend.app import app


class FakeFunnelTransport:
    def __init__(self):
        self.calls = []

    async def call(self, method, params):
        self.calls.append((method, params))
        if method == "crm.status.list":
            return {
                "result": [
                    {"ID": "1", "ENTITY_ID": "STATUS", "STATUS_ID": "NEW", "NAME": "New", "SORT": "10"},
                    {"ID": "2", "ENTITY_ID": "STATUS", "STATUS_ID": "PAID", "NAME": "To'lov qilindi", "SORT": "20"},
                ]
            }
        return {
            "result": [
                {"ID": "101", "STATUS_ID": "PAID", "PHONE": [{"VALUE": "+998901112233"}]},
                {"ID": "102", "STATUS_ID": "NEW", "PHONE": [{"VALUE": "+998900000000"}]},
            ]
        }


def test_crm_funnel_groups_by_audience_via_phone_join(monkeypatch, tmp_path):
    storage = tmp_path / "storage"
    storage.mkdir()
    (storage / "funnel_events.jsonl").write_text(
        '{"eventName":"bot_start","aud":"ai","phone":"+998901112233","telegramUserId":"tg1"}\n',
        encoding="utf-8",
    )
    transport = FakeFunnelTransport()
    monkeypatch.setenv("BITRIX24_WEBHOOK_URL", "https://example.bitrix24.com/rest/1/secret/")
    monkeypatch.delenv("BITRIX_PAID_STATUS_IDS", raising=False)  # exercise the label heuristic, not the machine's .env
    monkeypatch.setattr(app_module, "build_bitrix_transport", lambda config: transport)
    monkeypatch.setattr(app_module, "FUNNEL_EVENTS_STORAGE_DIR", storage)
    app_module._CRM_FUNNEL_CACHE.clear()
    client = TestClient(app)

    res = client.get("/api/crm/funnel?days=30")
    body = res.json()

    assert res.status_code == 200
    assert body["ok"] is True
    assert body["audiences"]["ai"]["PAID"] == 1
    assert body["audiences"]["unattributed"]["NEW"] == 1
    assert body["matchRate"] == 0.5
    assert body["paidStageIds"] == ["PAID"]
    # read-only: only list methods are ever called
    assert {call[0] for call in transport.calls} <= {"crm.lead.list", "crm.status.list"}


def test_crm_funnel_reports_unconfigured_without_calling_bitrix(monkeypatch):
    monkeypatch.delenv("BITRIX24_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("BITRIX24_PORTAL_URL", raising=False)
    monkeypatch.delenv("BITRIX24_USER_ID", raising=False)
    monkeypatch.delenv("BITRIX24_WEBHOOK_KEY", raising=False)
    app_module._CRM_FUNNEL_CACHE.clear()
    client = TestClient(app)

    res = client.get("/api/crm/funnel?days=30")

    assert res.status_code == 200
    assert res.json()["ok"] is False


def test_crm_funnel_honors_paid_status_ids_env(monkeypatch, tmp_path):
    storage = tmp_path / "storage"
    storage.mkdir()
    (storage / "funnel_events.jsonl").write_text("", encoding="utf-8")
    monkeypatch.setenv("BITRIX24_WEBHOOK_URL", "https://example.bitrix24.com/rest/1/secret/")
    monkeypatch.setenv("BITRIX_PAID_STATUS_IDS", "NEW")  # force NEW to be the configured paid stage
    monkeypatch.setattr(app_module, "build_bitrix_transport", lambda config: FakeFunnelTransport())
    monkeypatch.setattr(app_module, "FUNNEL_EVENTS_STORAGE_DIR", storage)
    app_module._CRM_FUNNEL_CACHE.clear()
    client = TestClient(app)

    body = client.get("/api/crm/funnel?days=30").json()

    assert body["paidStageIds"] == ["NEW"]  # env override wins over the label heuristic
