from fastapi.testclient import TestClient

import backend.app as app_module
from backend.app import app


def test_agent_chat_exposes_handoffs_and_quality_to_clients():
    client = TestClient(app)

    response = client.post(
        "/api/agent/chat",
        json={"message": "Ask Meta AI Advisor what previous ad sets and creatives should teach us."},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["activeAgent"] == "meta_ai_advisor"
    assert payload["agentHandoffs"]
    assert payload["agentHandoffs"][0]["toAgent"] == "meta_ai_strategist"
    assert payload["quality"]["status"] == "usable"
    assert payload["quality"]["score"] >= 95


def test_agent_chat_answers_campaign_specific_audience_from_raw_knowledge(monkeypatch):
    monkeypatch.setattr(app_module, "generate_chat_answer", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        app_module,
        "load_knowledge_base",
        lambda: {
            "raw": {
                "campaigns": [{"id": "cmp_1", "name": "DA - SHAHLOAI - VSL 2 - 26.04.2026 Y"}],
                "ads": [
                    {
                        "id": "ad_1",
                        "name": "VID - 08",
                        "campaign_id": "cmp_1",
                        "adset_id": "as_ai",
                        "creative": {"id": "cr_1", "thumbnail_url": "https://example.com/thumb.jpg", "video_id": "vid_1"},
                    }
                ],
                "insights": {
                    "base": [
                        {
                            "campaign_id": "cmp_1",
                            "campaign_name": "DA - SHAHLOAI - VSL 2 - 26.04.2026 Y",
                            "adset_id": "as_ai",
                            "adset_name": "TOF - UZB - 18 - 45 - ALL - AD+ [AI]",
                            "ad_id": "ad_1",
                            "ad_name": "VID - 08",
                            "spend": "100",
                            "clicks": "2000",
                            "actions": [{"action_type": "lead", "value": "1000"}],
                        },
                        {
                            "campaign_id": "cmp_1",
                            "campaign_name": "DA - SHAHLOAI - VSL 2 - 26.04.2026 Y",
                            "adset_id": "as_business",
                            "adset_name": "TOF - UZB - 18 - 45 - ALL - AD+ [BUSINESS]",
                            "ad_id": "ad_2",
                            "ad_name": "VID - 07",
                            "spend": "80",
                            "clicks": "1000",
                            "actions": [{"action_type": "lead", "value": "400"}],
                        },
                    ]
                },
            },
            "analysis": {"summary": {"spend": 180, "clicks": 3000, "leads": 1400}},
        },
    )
    client = TestClient(app)

    response = client.post(
        "/api/agent/chat",
        json={"message": "Which audience should we scale from DA - SHAHLOAI - VSL 2 - 26.04.2026 Y and why?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["activeAgent"] == "audience"
    assert "TOF - UZB - 18 - 45 - ALL - AD+ [AI]" in payload["answer"]
    assert "$0.10" in payload["answer"]
    assert "campaign_specific_analysis" in payload["sources"]
