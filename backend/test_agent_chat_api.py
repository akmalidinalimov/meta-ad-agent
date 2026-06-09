from fastapi.testclient import TestClient

import backend.routers.agents as agents_module
from backend.app import app
from backend.meta_live import LiveAccount


def test_agent_chat_roster_uses_live_meta_data(monkeypatch):
    monkeypatch.setattr(agents_module, "generate_chat_answer", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        agents_module,
        "load_knowledge_base",
        lambda: {"raw": {"campaigns": [{"id": "stale", "name": "Stale Cached", "status": "ACTIVE"}]}},
    )

    live = LiveAccount(
        campaigns=[
            {"id": "live_1", "name": "Live Winner", "effective_status": "ACTIVE", "objective": "OUTCOME_LEADS"},
            {"id": "live_2", "name": "Live Paused", "effective_status": "PAUSED"},
        ],
        adsets=[],
        ads=[],
        source="live",
        fetched_at="now",
    )

    async def fake_live_account(**kwargs):
        return live

    monkeypatch.setattr(agents_module, "get_live_account", fake_live_account)
    client = TestClient(app)

    response = client.post("/api/agent/chat", json={"message": "what campaigns are active?"})

    assert response.status_code == 200
    payload = response.json()
    assert "Live Winner" in payload["answer"]
    assert "Stale Cached" not in payload["answer"]
    assert "live Meta data was unavailable" not in payload["answer"]
    assert "meta_live" in payload["sources"]


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
    monkeypatch.setattr(agents_module, "generate_chat_answer", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        agents_module,
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
    monkeypatch.setattr(agents_module, "generate_chat_answer", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        agents_module,
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
    monkeypatch.setattr(agents_module, "generate_chat_answer", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        agents_module,
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
    monkeypatch.setattr(agents_module, "generate_chat_answer", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        agents_module,
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


def test_agent_chat_uses_placement_specialist_ranking_from_knowledge_base(monkeypatch):
    monkeypatch.setattr(agents_module, "generate_chat_answer", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        agents_module,
        "load_knowledge_base",
        lambda: {
            "analysis": {
                "summary": {"spend": 300, "clicks": 3000, "leads": 1200},
                "placements": [
                    {
                        "label": "instagram / reels",
                        "spend": 180,
                        "clicks": 2200,
                        "leads": 950,
                        "purchases": 0,
                        "cpc": 0.0818,
                        "cpl": 0.1895,
                        "leadRateFromClick": 43.2,
                        "qualityScore": 94,
                    },
                    {
                        "label": "facebook / feed",
                        "spend": 120,
                        "clicks": 800,
                        "leads": 250,
                        "purchases": 0,
                        "cpc": 0.15,
                        "cpl": 0.48,
                        "leadRateFromClick": 31.25,
                        "qualityScore": 68,
                    },
                ],
            }
        },
    )
    client = TestClient(app)

    response = client.post("/api/agent/chat", json={"message": "Which placements should we use or avoid?"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["activeAgent"] == "placement"
    assert "Placement specialist ranking" in payload["answer"]
    assert "instagram / reels" in payload["answer"]
    assert "facebook / feed" in payload["answer"]
    assert "separate Instagram placements from Facebook tests" in payload["answer"]
    assert "Telegram START and CRM quality" in payload["answer"]


def test_agent_chat_uses_funnel_specialist_diagnosis_from_knowledge_base(monkeypatch):
    monkeypatch.setattr(agents_module, "generate_chat_answer", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        agents_module,
        "load_knowledge_base",
        lambda: {
            "raw": {
                "insights": {
                    "base": [
                        {
                            "spend": "100",
                            "clicks": "1000",
                            "actions": [
                                {"action_type": "landing_page_view", "value": "620"},
                                {"action_type": "lead", "value": "310"},
                            ],
                        }
                    ]
                }
            },
            "analysis": {
                "summary": {
                    "spend": 100,
                    "clicks": 1000,
                    "leads": 310,
                    "purchases": 0,
                    "cpc": 0.1,
                    "cpl": 0.3226,
                    "leadRateFromClick": 31,
                }
            },
        },
    )
    client = TestClient(app)

    response = client.post("/api/agent/chat", json={"message": "Where is the biggest funnel leak?"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["activeAgent"] == "funnel"
    assert "Funnel specialist diagnosis" in payload["answer"]
    assert "landing visit rate 62.0%" in payload["answer"]
    assert "landing lead rate 50.0%" in payload["answer"]
    assert "Telegram START rate" in payload["answer"]
    assert "CRM purchase data" in payload["answer"]


def _live_with_config(monkeypatch):
    """Stub get_live_account with a campaign that has full targeting + an A/B study."""
    live = LiveAccount(
        campaigns=[{"id": "cmp_1", "name": "Live VSL", "objective": "OUTCOME_LEADS", "buying_type": "AUCTION"}],
        adsets=[
            {
                "id": "as_1",
                "campaign_id": "cmp_1",
                "name": "TOF - UZB - [AI]",
                "optimization_goal": "OFFSITE_CONVERSIONS",
                "targeting": {
                    "age_min": 18,
                    "age_max": 45,
                    "geo_locations": {"cities": [{"name": "Tashkent"}]},
                    "publisher_platforms": ["instagram"],
                    "instagram_positions": ["reels"],
                    "flexible_spec": [{"interests": [{"name": "Entrepreneurship"}]}],
                },
            }
        ],
        ads=[],
        source="live",
        fetched_at="now",
        adstudies=[
            {"id": "s1", "name": "VSL split test", "cells": {"data": [{"adsets": {"data": [{"id": "as_1"}]}}]}}
        ],
        saved_audiences=[],
    )

    async def fake_live_account(**kwargs):
        return live

    monkeypatch.setattr(agents_module, "get_live_account", fake_live_account)


def test_agent_chat_config_question_returns_live_config_not_performance(monkeypatch):
    monkeypatch.setattr(agents_module, "generate_chat_answer", lambda *a, **k: None)
    monkeypatch.setattr(agents_module, "load_knowledge_base", lambda: {"raw": {"campaigns": []}, "analysis": {}})
    _live_with_config(monkeypatch)
    client = TestClient(app)

    response = client.post(
        "/api/agent/chat",
        json={"message": "what audience and interests did Live VSL use? was A/B enabled?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "Configuration for Live VSL" in payload["answer"]
    assert "Entrepreneurship" in payload["answer"]
    assert "A/B test: enabled (VSL split test)" in payload["answer"]
    assert "Tashkent" in payload["answer"]
    # NOT the performance ranking.
    assert "audience ranking" not in payload["answer"].lower()
    assert "campaign_specific_analysis" in payload["sources"]
    assert "meta_live" in payload["sources"]


def test_agent_chat_performance_question_still_returns_ranking(monkeypatch):
    monkeypatch.setattr(agents_module, "generate_chat_answer", lambda *a, **k: None)
    monkeypatch.setattr(
        agents_module,
        "load_knowledge_base",
        lambda: {
            "raw": {
                "campaigns": [{"id": "cmp_1", "name": "Live VSL"}],
                "insights": {
                    "base": [
                        {
                            "campaign_id": "cmp_1",
                            "adset_id": "as_ai",
                            "adset_name": "TOF - UZB - [AI]",
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
    _live_with_config(monkeypatch)
    client = TestClient(app)

    response = client.post(
        "/api/agent/chat",
        json={"message": "Rank the creative videos from Live VSL by performance"},
    )

    assert response.status_code == 200
    payload = response.json()
    # Performance path wins for a perf question even though config data exists.
    assert "Configuration for" not in payload["answer"]
    assert payload["activeAgent"] == "creative"


def test_agent_chat_autonomous_autoexecute_appends_created_objects(monkeypatch):
    monkeypatch.setattr(agents_module, "generate_chat_answer", lambda *a, **k: None)
    monkeypatch.setattr(agents_module, "load_knowledge_base", lambda: {"analysis": {"summary": {}}})

    live = LiveAccount(campaigns=[], adsets=[], ads=[], source="live", fetched_at="now")

    async def fake_live_account(**kwargs):
        return live

    monkeypatch.setattr(agents_module, "get_live_account", fake_live_account)

    saved_approval = {
        "id": "autonomous_x",
        "actionType": "create_paused_campaign_structure",
        "status": "needs_review",
        "guardrailResult": "pass",
        "after": {"campaign": {"name": "Best Guess - DRAFT"}, "adsets": [{"name": "AI - DRAFT", "daily_budget": 10000}]},
        "createdAt": "now",
    }

    def fake_orchestrate(question, **kwargs):
        return {
            "activeAgent": "orchestrator",
            "routeReason": "autonomous",
            "answer": "I built a best-guess paused campaign on my own.",
            "sources": ["opportunity_finder"],
            "suggestedQuestions": [],
            "agentHandoffs": [],
            "autonomous": True,
            "generatedApprovalRequest": saved_approval,
        }

    monkeypatch.setattr(agents_module, "orchestrate_agent_chat", fake_orchestrate)
    monkeypatch.setattr(agents_module, "get_pending", lambda op_key: None)
    monkeypatch.setattr(agents_module, "set_pending", lambda *a, **k: None)
    monkeypatch.setattr(agents_module, "clear_pending", lambda *a, **k: None)
    monkeypatch.setattr(
        agents_module,
        "auto_execute_paused",
        lambda approval_id: {
            "ok": True,
            "created": [
                {"level": "campaign", "id": "cmp_live", "name": "Best Guess - DRAFT"},
                {"level": "adset", "id": "as_live", "name": "AI - DRAFT"},
            ],
            "blocked": None,
        },
    )
    monkeypatch.setattr(agents_module, "_ad_account_id", lambda: "act_555")

    client = TestClient(app)
    response = client.post(
        "/api/agent/chat",
        json={"message": "just do it, you decide and create a test on your own"},
    )

    assert response.status_code == 200
    answer = response.json()["answer"]
    assert "Created in Meta as PAUSED" in answer
    assert "1 campaign" in answer
    assert "1 ad set" in answer
    assert "adsmanager.facebook.com" in answer
    assert "act=555" in answer


def test_agent_chat_pending_refinement_updates_same_approval(monkeypatch):
    monkeypatch.setattr(agents_module, "generate_chat_answer", lambda *a, **k: None)
    monkeypatch.setattr(agents_module, "load_knowledge_base", lambda: {"analysis": {"summary": {}}})

    # Operator has an in-flight autonomous draft; patch the names agents.py imported.
    set_calls = []
    clear_calls = []
    monkeypatch.setattr(
        agents_module, "get_pending", lambda op_key: {"approvalId": "autonomous_x", "budget": 100.0, "audiences": ["AI"]}
    )
    monkeypatch.setattr(agents_module, "set_pending", lambda op_key, pointer: set_calls.append((op_key, pointer)))
    monkeypatch.setattr(agents_module, "clear_pending", lambda op_key: clear_calls.append(op_key))

    rebuilt = {
        "id": "autonomous_x",
        "after": {"campaign": {"name": "Best Guess - DRAFT"}, "adsets": [{"name": "AI - DRAFT", "daily_budget": 15000}]},
    }
    captured = {}

    def fake_build(knowledge, playbooks, **kwargs):
        captured["budget"] = kwargs.get("budget")
        captured["approval_id"] = kwargs.get("approval_id")
        return rebuilt

    updated = {}

    def fake_update(approval_id, patch, **kwargs):
        updated["approval_id"] = approval_id
        return {**patch, "id": approval_id, "after": patch.get("after", rebuilt["after"])}

    import backend.opportunity_finder as of_module

    monkeypatch.setattr(of_module, "build_autonomous_campaign", fake_build)
    monkeypatch.setattr(agents_module.approval_store, "update_approval_request", fake_update)

    client = TestClient(app)
    response = client.post(
        "/api/agent/chat",
        json={"message": "make it $150/day in Tashkent"},
    )

    assert response.status_code == 200
    answer = response.json()["answer"]
    assert "refined your draft" in answer.lower()
    # Same approvalId rebuilt in place with the new budget; pending refreshed (set), not cleared.
    assert captured["approval_id"] == "autonomous_x"
    assert captured["budget"] == 150.0
    assert updated["approval_id"] == "autonomous_x"
    assert set_calls and set_calls[0][1]["approvalId"] == "autonomous_x"
