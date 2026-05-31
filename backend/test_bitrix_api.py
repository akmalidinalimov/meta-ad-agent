from fastapi.testclient import TestClient

import backend.app as app_module
from backend.app import app
from backend.crm_store import list_crm_leads


class FakeBitrixTransport:
    async def call(self, method, params):
        return {
            "result": [
                {
                    "ID": "101",
                    "TITLE": "AI course lead",
                    "STATUS_ID": "NEW",
                    "UTM_CAMPAIGN": "cmp_income",
                    "UF_CRM_VISITOR_ID": "v_abc123",
                }
            ]
        }


class FailingBitrixTransport:
    async def call(self, method, params):
        raise RuntimeError("Bitrix24 API returned HTTP 401.")


def bind_tmp_crm(monkeypatch, tmp_path):
    storage_dir = tmp_path / "storage"
    monkeypatch.setattr(app_module, "CRM_STORAGE_DIR", storage_dir)
    return storage_dir


def test_bitrix_status_reports_missing_webhook(monkeypatch):
    monkeypatch.delenv("BITRIX24_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("BITRIX24_PORTAL_URL", raising=False)
    monkeypatch.delenv("BITRIX24_USER_ID", raising=False)
    monkeypatch.delenv("BITRIX24_WEBHOOK_KEY", raising=False)
    client = TestClient(app)

    response = client.get("/api/crm/bitrix/status")

    assert response.status_code == 200
    assert response.json()["configured"] is False
    assert "webhook" in response.json()["message"].lower()


def test_bitrix_import_saves_normalized_leads(monkeypatch, tmp_path):
    storage_dir = bind_tmp_crm(monkeypatch, tmp_path)
    monkeypatch.setenv("BITRIX24_WEBHOOK_URL", "https://example.bitrix24.com/rest/1/secret/")
    monkeypatch.setattr(app_module, "build_bitrix_transport", lambda config: FakeBitrixTransport())
    client = TestClient(app)

    response = client.post("/api/crm/bitrix/import")
    saved = list_crm_leads(storage_dir=storage_dir)

    assert response.status_code == 200
    assert response.json()["imported"] == 1
    assert saved[0]["crmLeadId"] == "101"
    assert saved[0]["visitorId"] == "v_abc123"


def test_bitrix_import_returns_sanitized_upstream_error(monkeypatch, tmp_path):
    bind_tmp_crm(monkeypatch, tmp_path)
    monkeypatch.setenv("BITRIX24_WEBHOOK_URL", "https://example.bitrix24.com/rest/1/secret/")
    monkeypatch.setattr(app_module, "build_bitrix_transport", lambda config: FailingBitrixTransport())
    client = TestClient(app)

    response = client.post("/api/crm/bitrix/import")

    assert response.status_code == 502
    assert response.json()["detail"] == "Bitrix24 import failed: Bitrix24 API returned HTTP 401."
