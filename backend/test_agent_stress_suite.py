from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import backend.routers.agents as agents_module
from backend.app import app


def stress_knowledge() -> dict:
    return {
        "raw": {
            "campaigns": [{"id": "cmp_vsl", "name": "DA - SHAHLOAI - VSL 2 - 26.04.2026 Y"}],
            "ads": [
                {
                    "id": "ad_housewife",
                    "name": "VID - Housewife viral",
                    "campaign_id": "cmp_vsl",
                    "adset_id": "as_broad",
                    "creative": {"id": "cr_housewife", "thumbnail_url": "https://example.com/housewife.jpg", "video_id": "video_housewife"},
                },
                {
                    "id": "ad_business",
                    "name": "VID - Business proof",
                    "campaign_id": "cmp_vsl",
                    "adset_id": "as_business",
                    "creative": {"id": "cr_business", "thumbnail_url": "https://example.com/business.jpg", "video_id": "video_business"},
                },
            ],
            "insights": {
                "base": [
                    {
                        "campaign_id": "cmp_vsl",
                        "campaign_name": "DA - SHAHLOAI - VSL 2 - 26.04.2026 Y",
                        "adset_id": "as_broad",
                        "adset_name": "TOF - UZB - 18 - 45 - ALL - AD+ [BROAD]",
                        "ad_id": "ad_housewife",
                        "ad_name": "VID - Housewife viral",
                        "spend": "120",
                        "clicks": "2400",
                        "actions": [
                            {"action_type": "landing_page_view", "value": "1700"},
                            {"action_type": "lead", "value": "900"},
                        ],
                    },
                    {
                        "campaign_id": "cmp_vsl",
                        "campaign_name": "DA - SHAHLOAI - VSL 2 - 26.04.2026 Y",
                        "adset_id": "as_business",
                        "adset_name": "TOF - UZB - 25 - 45 - ALL - AD+ [BUSINESS/SMM]",
                        "ad_id": "ad_business",
                        "ad_name": "VID - Business proof",
                        "spend": "160",
                        "clicks": "1200",
                        "actions": [
                            {"action_type": "landing_page_view", "value": "1050"},
                            {"action_type": "lead", "value": "420"},
                            {"action_type": "purchase", "value": "3"},
                        ],
                    },
                ]
            },
        },
        "analysis": {
            "summary": {
                "spend": 280,
                "clicks": 3600,
                "leads": 1320,
                "purchases": 3,
                "ctr": 2.8,
                "cpc": 0.0778,
                "cpl": 0.2121,
                "leadRateFromClick": 36.7,
                "purchaseRateFromClick": 0.08,
            },
            "topAds": [
                {
                    "label": "ad_housewife / VID - Housewife viral",
                    "keys": {"ad_id": "ad_housewife", "ad_name": "VID - Housewife viral"},
                    "spend": 120,
                    "clicks": 2400,
                    "leads": 900,
                    "purchases": 0,
                    "cpc": 0.05,
                    "cpl": 0.1333,
                    "qualityScore": 72,
                },
                {
                    "label": "ad_business / VID - Business proof",
                    "keys": {"ad_id": "ad_business", "ad_name": "VID - Business proof"},
                    "spend": 160,
                    "clicks": 1200,
                    "leads": 420,
                    "purchases": 3,
                    "cpc": 0.1333,
                    "cpl": 0.381,
                    "qualityScore": 85,
                },
            ],
            "audience": {
                "ageGender": [
                    {"label": "25-34 / all", "spend": 140, "clicks": 1500, "leads": 550, "purchases": 2, "cpc": 0.093, "cpl": 0.254, "leadRateFromClick": 36.7},
                    {"label": "18-24 / all", "spend": 80, "clicks": 1400, "leads": 620, "purchases": 0, "cpc": 0.057, "cpl": 0.129, "leadRateFromClick": 44.3},
                ],
                "countries": [{"label": "UZ", "spend": 280, "clicks": 3600, "leads": 1320, "purchases": 3, "cpl": 0.212}],
                "regions": [{"label": "Tashkent Region", "spend": 170, "clicks": 1800, "leads": 680, "purchases": 3, "cpl": 0.25}],
                "interests": [
                    {"label": "Business", "spend": 160, "clicks": 1200, "leads": 420, "purchases": 3, "cpc": 0.1333, "cpl": 0.381, "leadRateFromClick": 35},
                    {"label": "Broad / no explicit interests", "spend": 120, "clicks": 2400, "leads": 900, "purchases": 0, "cpc": 0.05, "cpl": 0.1333, "leadRateFromClick": 37.5},
                ],
            },
            "placements": [
                {"label": "instagram / reels", "spend": 200, "clicks": 2600, "leads": 1020, "purchases": 3, "cpc": 0.0769, "cpl": 0.196, "leadRateFromClick": 39.2, "qualityScore": 88},
                {"label": "facebook / feed", "spend": 80, "clicks": 1000, "leads": 300, "purchases": 0, "cpc": 0.08, "cpl": 0.267, "leadRateFromClick": 30, "qualityScore": 52},
            ],
            "recommendations": [
                {"area": "Creative", "title": "Audit viral lead volume against buyer quality", "reason": "Housewife creative leads are cheap but purchases are absent."},
                {"area": "Audience", "title": "Use business/SMM as a buyer-quality challenger", "reason": "Business proof creative has purchase evidence."},
            ],
            "lessons": [
                "Cheap clicks alone are not enough; compare Telegram START and CRM quality.",
                "Instagram placements are the strongest cold-start hypothesis for Uzbekistan.",
            ],
        },
    }


@pytest.fixture()
def stress_client(monkeypatch):
    import backend.dashboard_service as dashboard_service_module

    monkeypatch.setattr(agents_module, "load_knowledge_base", stress_knowledge)
    monkeypatch.setattr(agents_module, "generate_chat_answer", lambda *args, **kwargs: None)
    monkeypatch.setattr(agents_module, "save_playbook", lambda playbook: playbook)
    monkeypatch.setattr(agents_module, "load_playbooks", lambda: [])
    # build_dashboard() reads load_knowledge_base from dashboard_service, so patch it
    # there too and reset the module-level dashboard cache for test isolation.
    monkeypatch.setattr(dashboard_service_module, "load_knowledge_base", stress_knowledge)
    dashboard_service_module.DASHBOARD_CACHE.update({"key": None, "payload": None})
    return TestClient(app)


@pytest.mark.parametrize(
    ("message", "agent", "must_include"),
    [
        (
            "You are a strict Meta ads buyer. Should we scale the cheap housewife creative or the more expensive business proof creative, and why?",
            "creative",
            ["Creative specialist ranking", "Avoid scaling blindly", "purchase"],
        ),
        (
            "Which audience should we target if cheap leads are not enough and the course costs 3,690,000 UZS?",
            "audience",
            ["Audience specialist ranking", "Business", "Telegram START quality"],
        ),
        (
            "If Instagram Reels looks good but Facebook Feed is cheaper, should we mix placements or isolate them?",
            "placement",
            ["Placement specialist ranking", "separate Instagram placements from Facebook tests", "facebook / feed"],
        ),
        (
            "Diagnose the funnel like a performance marketer: are we losing people before landing, before registration, or after lead?",
            "funnel",
            ["Funnel specialist diagnosis", "landing visit rate", "CRM purchase data"],
        ),
        (
            "Create a plan for one income VSL and one business automation VSL, $100 each, but do not execute until approved.",
            "orchestrator",
            ["approval-ready campaign plan", "I will not execute", "Segments"],
        ),
        (
            "Rename campaign 120123 to STRESS TEST - DO NOT PUBLISH, but only if it stays approval-gated.",
            "execution",
            ["approval-gated", "I will not execute it until you approve", "120123"],
        ),
        (
            "Meta AI says creative efficiency is high. How should the Meta AI Advisor use that without ignoring Telegram and CRM quality?",
            "meta_ai_advisor",
            ["read-only", "Telegram", "CRM"],
        ),
        (
            "Give me a monitoring decision if CPL improves but Telegram quality is not proven yet.",
            "monitoring",
            ["every four hours", "approval", "recommend"],
        ),
        (
            "Design an A/B test for proof-led creative versus viral humor without increasing spend blindly.",
            "experiment",
            ["experiment", "Success metric", "avoid"],
        ),
    ],
)
def test_agent_stress_questions_route_and_answer_with_actionable_guardrails(stress_client, message, agent, must_include):
    response = stress_client.post("/api/agent/chat", json={"message": message})

    assert response.status_code == 200
    payload = response.json()
    assert payload["activeAgent"] == agent
    assert payload["quality"]["score"] >= 90
    assert payload["sources"]
    assert payload["suggestedQuestions"]
    for expected in must_include:
        assert expected.lower() in payload["answer"].lower()
    if agent in {"orchestrator", "execution"}:
        assert payload["agentDecision"]["approvalRequired"] is True


def test_stress_suite_multi_specialist_campaign_question_uses_orchestrator_handoffs(stress_client):
    response = stress_client.post(
        "/api/agent/chat",
        json={
            "message": (
                "Build the next campaign recommendation by combining the top audience, top creative, placements, funnel leakage, "
                "monitoring rules, and approval-safe execution. Be skeptical about cheap leads."
            )
        },
    )

    payload = response.json()
    handoff_targets = {handoff["toAgent"] for handoff in payload["agentHandoffs"]}
    assert response.status_code == 200
    assert payload["activeAgent"] == "orchestrator"
    assert {"audience", "creative", "placement", "funnel", "experiment"}.issubset(handoff_targets)
    assert payload["agentDecision"]["approvalRequired"] is True
    assert "Meta-side data" in payload["answer"]
