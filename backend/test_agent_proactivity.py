import asyncio

from fastapi.testclient import TestClient

import backend.routers.agents as agents_module
from backend.app import app
from backend.llm_reasoner import refine_text
from backend.proactive_insights import build_proactive_insights
from backend.specialist_findings import collect_findings, confidence_for, evidence_score


def rich_knowledge():
    base = [
        {
            "campaign_id": "cmp_1", "campaign_name": "DA - VSL 2", "adset_id": "as_ai",
            "adset_name": "TOF - UZB - [AI]", "ad_id": "ad_8", "ad_name": "VID - 08",
            "spend": "600", "clicks": "18000", "impressions": "400000",
            "actions": [{"action_type": "lead", "value": "15000"}],
        },
        {
            "campaign_id": "cmp_1", "campaign_name": "DA - VSL 2", "adset_id": "as_biz",
            "adset_name": "TOF - UZB - [BUSINESS]", "ad_id": "ad_7", "ad_name": "VID - 07",
            "spend": "20", "clicks": "500", "impressions": "12000",
            "actions": [{"action_type": "lead", "value": "450"}],
        },
    ]
    return {
        "raw": {
            "campaigns": [{"id": "cmp_1", "name": "DA - VSL 2"}],
            "ads": [{"id": "ad_8", "creative": {"id": "c8", "thumbnail_url": "http://t/8.jpg", "video_id": "v8"}}],
            "insights": {"base": base},
        },
        "analysis": {
            "summary": {"spend": 620, "clicks": 18500, "leads": 15450, "purchases": 0, "cpl": 0.04},
            "topAds": [
                {"label": "VID - 08", "keys": {"ad_id": "ad_8", "ad_name": "VID - 08"}, "spend": 600, "clicks": 18000, "leads": 15000, "purchases": 0, "cpl": 0.04, "qualityScore": 40},
            ],
            "placements": [
                {"label": "instagram / reels", "spend": 400, "clicks": 12000, "leads": 11000, "purchases": 0, "cpl": 0.036, "leadRateFromClick": 91.0, "qualityScore": 40},
                {"label": "facebook / feed", "spend": 220, "clicks": 6500, "leads": 600, "purchases": 0, "cpl": 0.36, "leadRateFromClick": 9.0, "qualityScore": 12},
            ],
            "audience": {"interests": [{"label": "Artificial intelligence", "spend": 300, "clicks": 9000, "leads": 8000, "cpl": 0.0375, "leadRateFromClick": 88.0}]},
            "lessons": ["Lead events exist but purchase events are missing or not attributed."],
        },
    }


def test_evidence_score_varies_with_sample_and_purchase_proof():
    strong = evidence_score({"clicks": 1000, "spend": 100, "purchases": 5}, 3)
    thin = evidence_score({"clicks": 10, "spend": 1, "purchases": 0}, 1)
    assert strong > thin
    assert confidence_for({"clicks": 1000, "spend": 100}) == "high"
    assert confidence_for({"clicks": 10, "spend": 1}) == "low"


def test_collect_findings_produces_real_evidence_scored_findings():
    findings = collect_findings(rich_knowledge())
    assert set(findings) >= {"audit", "audience", "creative", "placement", "funnel"}
    # Best ad set resolved from raw rows, evidence score reflects strong sample.
    assert "[AI]" in findings["audience"]["best"]["label"]
    assert findings["audience"]["evidenceScore"] > 5
    # No purchases anywhere -> every specialist surfaces that as a risk somewhere.
    assert any("purchase" in risk.lower() for risk in findings["audience"]["risks"])


def test_collect_findings_empty_without_knowledge():
    assert collect_findings(None) == {}


def test_proactive_insights_surface_traffic_magnet_and_waste():
    insights = build_proactive_insights(rich_knowledge())
    assert insights, "expected proactive insights"
    titles = " ".join(i["title"] for i in insights)
    assert "Traffic magnet" in titles  # high-lead zero-buyer creative
    assert any(i["agent"] == "placement" for i in insights)  # placement waste
    # Highest priority first.
    assert insights[0]["priority"] == "high"


def test_agent_insights_endpoint(monkeypatch):
    monkeypatch.setattr(agents_module, "load_knowledge_base", rich_knowledge)
    client = TestClient(app)
    response = client.get("/api/agent/insights")
    assert response.status_code == 200
    assert len(response.json()["insights"]) >= 1


def test_agent_chat_proactively_recommends(monkeypatch):
    monkeypatch.setattr(agents_module, "load_knowledge_base", rich_knowledge)
    monkeypatch.setattr(agents_module, "generate_chat_answer", lambda *a, **k: None)
    client = TestClient(app)
    response = client.post("/api/agent/chat", json={"message": "What should we improve in the account?"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["proactiveInsights"]
    assert "recommendation" in payload["answer"].lower()


def test_refine_text_returns_input_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    out = asyncio.run(refine_text("Deterministic answer with $0.04 CPL.", instruction="improve"))
    assert out == "Deterministic answer with $0.04 CPL."
