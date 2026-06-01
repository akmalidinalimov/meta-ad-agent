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
    assert "Telegram START and CRM purchase data" in payload["answer"]
    assert "campaign_specific_analysis" in payload["sources"]


def test_agent_chat_uses_audience_specialist_ranking_from_knowledge_base(monkeypatch):
    monkeypatch.setattr(app_module, "generate_chat_answer", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        app_module,
        "load_knowledge_base",
        lambda: {
            "raw": {
                "campaigns": [{"id": "cmp_1", "name": "General campaign"}],
                "insights": {
                    "base": [
                        {
                            "campaign_id": "cmp_1",
                            "adset_id": "as_business",
                            "adset_name": "TOF - UZB - 25 - 44 - ALL - AD+ [BUSINESS]",
                            "spend": "120",
                            "clicks": "1200",
                            "actions": [{"action_type": "lead", "value": "600"}],
                        },
                        {
                            "campaign_id": "cmp_1",
                            "adset_id": "as_broad",
                            "adset_name": "TOF - UZB - 18 - 45 - ALL - AD+ [BROAD]",
                            "spend": "100",
                            "clicks": "900",
                            "actions": [{"action_type": "lead", "value": "250"}],
                        },
                    ]
                },
            },
            "analysis": {
                "summary": {"spend": 220, "clicks": 2100, "leads": 850},
                "audience": {
                    "ageGender": [
                        {
                            "label": "25-34 / female",
                            "spend": 90,
                            "clicks": 1000,
                            "leads": 500,
                            "purchases": 0,
                            "cpc": 0.09,
                            "cpl": 0.18,
                            "leadRateFromClick": 50,
                        }
                    ],
                    "interests": [
                        {
                            "label": "Business",
                            "spend": 120,
                            "clicks": 1200,
                            "leads": 600,
                            "purchases": 0,
                            "cpc": 0.1,
                            "cpl": 0.2,
                            "leadRateFromClick": 50,
                        }
                    ],
                },
            },
        },
    )
    client = TestClient(app)

    response = client.post("/api/agent/chat", json={"message": "Which audience and interests should we target next?"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["activeAgent"] == "audience"
    assert "Audience specialist ranking" in payload["answer"]
    assert "TOF - UZB - 25 - 44 - ALL - AD+ [BUSINESS]" in payload["answer"]
    assert "Top interest clusters" in payload["answer"]
    assert "Business" in payload["answer"]
    assert "Telegram START quality, CRM stages, and sales capacity" in payload["answer"]


def test_agent_chat_answers_campaign_specific_creatives_with_quality_warning(monkeypatch):
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
                        }
                    ]
                },
            },
            "analysis": {"summary": {"spend": 100, "clicks": 2000, "leads": 1000}},
        },
    )
    client = TestClient(app)

    response = client.post(
        "/api/agent/chat",
        json={"message": "Rank the creative videos from DA - SHAHLOAI - VSL 2 - 26.04.2026 Y"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["activeAgent"] == "creative"
    assert "VID - 08" in payload["answer"]
    assert "thumbnail+video" in payload["answer"]
    assert "Traffic magnet" in payload["answer"]
    assert "Telegram START and CRM quality" in payload["answer"]


def test_agent_chat_uses_creative_specialist_ranking_from_knowledge_base(monkeypatch):
    monkeypatch.setattr(app_module, "generate_chat_answer", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        app_module,
        "load_knowledge_base",
        lambda: {
            "raw": {
                "campaigns": [{"id": "cmp_1", "name": "General campaign"}],
                "ads": [
                    {
                        "id": "ad_scale",
                        "name": "VID - 08",
                        "creative": {
                            "id": "cr_scale",
                            "thumbnail_url": "https://example.com/scale.jpg",
                            "video_id": "video_scale",
                        },
                    },
                    {"id": "ad_weak", "name": "VID - 04", "creative": {"id": "cr_weak"}},
                ],
            },
            "analysis": {
                "summary": {"spend": 130, "clicks": 1700, "leads": 980},
                "topAds": [
                    {
                        "label": "ad_scale / VID - 08",
                        "keys": {"ad_id": "ad_scale", "ad_name": "VID - 08"},
                        "spend": 90,
                        "clicks": 1200,
                        "leads": 800,
                        "purchases": 0,
                        "cpc": 0.075,
                        "cpl": 0.1125,
                        "qualityScore": 74,
                    },
                    {
                        "label": "ad_weak / VID - 04",
                        "keys": {"ad_id": "ad_weak", "ad_name": "VID - 04"},
                        "spend": 40,
                        "clicks": 500,
                        "leads": 180,
                        "purchases": 0,
                        "cpc": 0.08,
                        "cpl": 0.222,
                        "qualityScore": 51,
                    },
                ],
            },
        },
    )
    client = TestClient(app)

    response = client.post("/api/agent/chat", json={"message": "Which creative should we scale or avoid?"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["activeAgent"] == "creative"
    assert "Creative specialist ranking" in payload["answer"]
    assert "VID - 08" in payload["answer"]
    assert "thumbnail and video ID available" in payload["answer"]
    assert "Traffic magnet to audit" in payload["answer"]
    assert "Avoid scaling blindly" in payload["answer"]
