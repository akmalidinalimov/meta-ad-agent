from fastapi.testclient import TestClient

import backend.routers.meta_ai as meta_ai_module
from backend.app import app
from backend.meta_ai_advisor import analyze_capture
from backend.meta_ai_capture_store import list_captures, save_capture
from backend.test_campaign_analysis import CAMPAIGN_NAME, sample_campaign_knowledge


SAMPLE_TEXT = (
    "Increase the budget on your Advantage+ audience. CTR is 2.1% and CPL is $0.04. "
    "Opportunity score is high. Consider testing new placements to expand reach."
)


def test_capture_store_round_trips(tmp_path):
    storage_dir = tmp_path / "storage"
    save_capture({"id": "c1", "createdAt": "2026-06-01T10:00:00Z", "sourceText": "a"}, storage_dir=storage_dir)
    save_capture({"id": "c2", "createdAt": "2026-06-02T10:00:00Z", "sourceText": "b"}, storage_dir=storage_dir)

    captures = list_captures(storage_dir=storage_dir)
    assert [c["id"] for c in captures] == ["c2", "c1"]  # most recent first


def test_advisor_summarizes_recommendations_evidence_and_blind_spots():
    result = analyze_capture({"sourceText": SAMPLE_TEXT})
    advisor = result["advisor"]

    assert any("budget" in rec.lower() for rec in advisor["recommendationSummary"])
    assert {"ctr", "cpl"}.issubset(set(advisor["evidenceUsed"]))
    # Meta AI text says nothing about Telegram START or buyers -> flagged as missed.
    assert "Telegram START quality" in advisor["whatItMissed"]
    assert "Paid course purchases / buyer quality" in advisor["whatItMissed"]
    assert advisor["trustLevel"] in {"high", "medium", "low"}


def test_strategist_scores_all_five_dimensions_and_adds_counterpoints():
    result = analyze_capture({"sourceText": SAMPLE_TEXT})
    strategist = result["strategist"]

    assert set(strategist["scores"]) == {
        "specificity",
        "metricAccuracy",
        "actionability",
        "businessRealism",
        "riskAwareness",
    }
    # Missing Telegram + buyer + purchasing-power signals pull business realism down.
    assert strategist["scores"]["businessRealism"] < 60
    assert any("Telegram" in point for point in strategist["businessCounterpoints"])


def test_strategist_metric_accuracy_rises_when_cpl_matches_campaign_reality():
    knowledge = sample_campaign_knowledge()
    capture = {"sourceText": SAMPLE_TEXT, "campaignName": CAMPAIGN_NAME}

    with_kb = analyze_capture(capture, knowledge=knowledge)
    without_kb = analyze_capture({"sourceText": SAMPLE_TEXT})

    assert with_kb["strategist"]["campaign"]["name"] == CAMPAIGN_NAME
    assert with_kb["strategist"]["scores"]["metricAccuracy"] > without_kb["strategist"]["scores"]["metricAccuracy"]
    assert any("Campaign reality" in point for point in with_kb["strategist"]["businessCounterpoints"])


def test_meta_ai_capture_api_stores_and_lists_with_analysis(monkeypatch, tmp_path):
    monkeypatch.setattr(meta_ai_module, "META_AI_STORAGE_DIR", tmp_path / "storage")
    monkeypatch.setattr(meta_ai_module, "load_knowledge_base", lambda: None)
    client = TestClient(app)

    response = client.post("/api/meta-ai/captures", json={"sourceText": SAMPLE_TEXT})
    assert response.status_code == 200
    capture = response.json()["capture"]
    assert capture["analysis"]["advisor"]["trustLevel"] in {"high", "medium", "low"}
    assert capture["analysis"]["strategist"]["overallScore"] >= 0

    listed = client.get("/api/meta-ai/captures").json()["captures"]
    assert len(listed) == 1
    assert listed[0]["id"] == capture["id"]


def test_meta_ai_capture_api_rejects_empty_text(monkeypatch, tmp_path):
    monkeypatch.setattr(meta_ai_module, "META_AI_STORAGE_DIR", tmp_path / "storage")
    monkeypatch.setattr(meta_ai_module, "load_knowledge_base", lambda: None)
    client = TestClient(app)

    response = client.post("/api/meta-ai/captures", json={"sourceText": "   "})
    assert response.status_code == 400
