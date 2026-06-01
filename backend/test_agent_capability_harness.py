from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import backend.app as app_module
from backend.app import app


def capability_knowledge() -> dict:
    return {
        "raw": {
            "campaigns": [{"id": "cmp_1", "name": "DA - SHAHLOAI - VSL 2 - 26.04.2026 Y"}],
            "ads": [
                {
                    "id": "ad_8",
                    "name": "VID - 08",
                    "campaign_id": "cmp_1",
                    "adset_id": "as_ai",
                    "creative": {"id": "cr_8", "thumbnail_url": "https://example.com/8.jpg", "video_id": "video_8"},
                },
                {
                    "id": "ad_7",
                    "name": "VID - 07",
                    "campaign_id": "cmp_1",
                    "adset_id": "as_business",
                    "creative": {"id": "cr_7", "thumbnail_url": "https://example.com/7.jpg", "video_id": "video_7"},
                },
            ],
            "insights": {
                "base": [
                    {
                        "campaign_id": "cmp_1",
                        "campaign_name": "DA - SHAHLOAI - VSL 2 - 26.04.2026 Y",
                        "adset_id": "as_ai",
                        "adset_name": "TOF - UZB - 18 - 45 - ALL - AD+ [AI]",
                        "ad_id": "ad_8",
                        "ad_name": "VID - 08",
                        "spend": "100",
                        "clicks": "2000",
                        "actions": [
                            {"action_type": "lead", "value": "1000"},
                            {"action_type": "landing_page_view", "value": "1800"},
                        ],
                    },
                    {
                        "campaign_id": "cmp_1",
                        "campaign_name": "DA - SHAHLOAI - VSL 2 - 26.04.2026 Y",
                        "adset_id": "as_business",
                        "adset_name": "TOF - UZB - 18 - 45 - ALL - AD+ [BUSINESS]",
                        "ad_id": "ad_7",
                        "ad_name": "VID - 07",
                        "spend": "80",
                        "clicks": "1000",
                        "actions": [
                            {"action_type": "lead", "value": "400"},
                            {"action_type": "landing_page_view", "value": "900"},
                        ],
                    },
                ]
            },
        },
        "analysis": {
            "summary": {
                "spend": 180,
                "clicks": 3000,
                "leads": 1400,
                "purchases": 0,
                "ctr": 2.4,
                "cpc": 0.06,
                "cpl": 0.128,
                "leadRateFromClick": 46.7,
            },
            "topAds": [
                {"label": "VID - 08", "spend": 100, "clicks": 2000, "leads": 1000, "purchases": 0, "qualityScore": 72},
                {"label": "VID - 07", "spend": 80, "clicks": 1000, "leads": 400, "purchases": 0, "qualityScore": 61},
            ],
            "audience": {
                "ageGender": [{"label": "25-34 / male", "spend": 120, "leads": 800, "purchases": 0, "qualityScore": 68}],
                "countries": [{"label": "UZ", "spend": 180, "leads": 1400, "purchases": 0, "qualityScore": 65}],
                "regions": [{"label": "Tashkent Region", "spend": 90, "leads": 650, "purchases": 0, "qualityScore": 64}],
                "interests": [{"label": "Artificial intelligence", "spend": 100, "leads": 1000, "purchases": 0, "qualityScore": 72}],
            },
            "placements": [{"label": "instagram / reels", "spend": 150, "leads": 1200, "purchases": 0, "qualityScore": 70}],
            "recommendations": [{"area": "Tracking", "title": "Connect Telegram START", "reason": "Lead quality is invisible."}],
            "lessons": ["Use Telegram START and CRM quality before scaling cheap leads."],
        },
    }


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(app_module, "load_knowledge_base", capability_knowledge)
    monkeypatch.setattr(app_module, "generate_chat_answer", lambda *args, **kwargs: None)
    monkeypatch.setattr(app_module, "save_playbook", lambda playbook: playbook)
    monkeypatch.setattr(
        app_module,
        "load_playbooks",
        lambda: [
            {
                "id": "pb_test",
                "name": "Capability Test",
                "primarySuccessMetric": "telegram_start",
                "segments": [
                    {
                        "id": "ai",
                        "name": "AI interest",
                        "startingBudgetUsd": 100,
                        "locations": ["Uzbekistan"],
                        "placements": ["instagram_reels"],
                        "interests": ["Artificial intelligence"],
                    }
                ],
                "rules": {"requiresApprovalForExecution": True, "maxDailyBudgetUsd": 300},
            }
        ],
    )
    return TestClient(app)


@pytest.mark.parametrize(
    ("message", "agent", "expected_text"),
    [
        (
            "Which audience should we scale from DA - SHAHLOAI - VSL 2 - 26.04.2026 Y and why?",
            "audience",
            "TOF - UZB - 18 - 45 - ALL - AD+ [AI]",
        ),
        (
            "Rank the creative videos from DA - SHAHLOAI - VSL 2 - 26.04.2026 Y",
            "creative",
            "VID - 08",
        ),
        (
            "Which placements worked for DA - SHAHLOAI - VSL 2 - 26.04.2026 Y?",
            "placement",
            "placement breakdowns",
        ),
        (
            "Can we calculate visit rate, landing lead rate, Telegram START, and CRM quality?",
            "funnel",
            "landing",
        ),
        (
            "What needs attention in monitoring right now?",
            "monitoring",
            "monitor",
        ),
        (
            "What A/B experiment should we run for VID - 08 versus VID - 07?",
            "experiment",
            "test",
        ),
        (
            "Use Meta AI Analyze for this campaign and compare it with our funnel data",
            "meta_ai_advisor",
            "Meta AI",
        ),
        (
            "Use the Meta AI captures to create a Meta-side strategy for ad sets and creatives",
            "meta_ai_strategist",
            "Meta-side strategy",
        ),
        (
            "Create a campaign with 1 VSL for AI income. Use $100 and optimize for Telegram START.",
            "orchestrator",
            "I will not execute",
        ),
        (
            "Rename campaign 120123 to QA SAFE TEST - DO NOT PUBLISH",
            "execution",
            "approval-gated",
        ),
    ],
)
def test_agent_capability_matrix_routes_and_answers(client, message, agent, expected_text):
    response = client.post("/api/agent/chat", json={"message": message})

    assert response.status_code == 200
    payload = response.json()
    assert payload["activeAgent"] == agent
    assert expected_text.lower() in payload["answer"].lower()
    assert payload["quality"]["score"] >= 90
    if agent in {"execution", "orchestrator"}:
        assert payload["agentDecision"]["approvalRequired"] is True


def test_agent_capability_matrix_execution_creates_review_not_live_action(client):
    response = client.post(
        "/api/agent/chat",
        json={"message": "Rename campaign 120123 to QA SAFE TEST - DO NOT PUBLISH"},
    )

    payload = response.json()
    assert payload["generatedApprovalRequest"]["status"] == "needs_review"
    assert payload["generatedApprovalRequest"]["target"]["id"] == "120123"
    assert payload["generatedApprovalRequest"]["after"]["name"] == "QA SAFE TEST - DO NOT PUBLISH"
