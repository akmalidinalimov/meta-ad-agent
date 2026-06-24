from fastapi.testclient import TestClient

import backend.routers.agents as agents_module
from backend.agent_council import run_strategy_council, should_run_strategy_council
from backend.app import app
from backend.test_strategy_generator import sample_knowledge, sample_playbook


def test_should_run_strategy_council_detects_proactive_agent_collaboration():
    assert should_run_strategy_council("Make all agents talk to each other and create the best possible campaign.")
    assert should_run_strategy_council("Create a campaign with audience, creative, placement, funnel, and experiment thinking.")
    assert not should_run_strategy_council("Which creative should we scale?")


def test_run_strategy_council_builds_multi_round_agent_session():
    session = run_strategy_council(
        "Run a strategy council for the next VSL campaign.",
        knowledge=sample_knowledge(),
        playbooks=[sample_playbook()],
    )

    assert session["approvalRequired"] is True
    assert session["executionSafety"]["publishBlocked"] is True
    assert len(session["agents"]) >= 9
    assert len(session["rounds"]) == 3
    assert len(session["events"]) >= 10
    # Scores are now evidence-based (vary with real data), not a constant ~9.5.
    assert 0 < session["averageScoreOutOf10"] <= 10
    assert 0 < session["quality"]["score"] <= 100
    assert len({score["scoreOutOf10"] for score in session["scores"]}) > 1
    assert "audienceDecision" in session["finalPlan"]
    assert "creativeDecision" in session["finalPlan"]
    assert "placementDecision" in session["finalPlan"]
    assert "executionDecision" in session["finalPlan"]
    assert session["finalPlan"]["executionDecision"]["canPublish"] is False


def test_council_without_evidence_does_not_name_fake_winners():
    # No knowledge synced: the council must not present hardcoded demo entities as
    # proven winners, and must flag itself as needs_refinement.
    session = run_strategy_council(
        "Run a strategy council for the next VSL campaign.",
        knowledge=None,
        playbooks=[],
    )
    assert session["hasEvidence"] is False
    assert session["quality"]["status"] == "needs_refinement"
    assert session["finalPlan"]["creativeDecision"]["topCreative"] == "no synced evidence"
    assert session["finalPlan"]["placementDecision"]["primary"] == "no synced evidence"


def test_agent_council_api_returns_visualizable_session(monkeypatch):
    monkeypatch.setattr(agents_module, "load_knowledge_base", sample_knowledge)
    monkeypatch.setattr(agents_module, "load_playbooks", lambda: [sample_playbook()])
    client = TestClient(app)

    response = client.post(
        "/api/agent/council",
        json={"message": "Run a strategy council and let agents critique each other for the next campaign."},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert 0 < payload["council"]["averageScoreOutOf10"] <= 10
    assert payload["council"]["events"][0].keys() >= {"fromAgent", "toAgent", "question", "answer"}


def test_agent_chat_attaches_council_for_multi_agent_strategy_request(monkeypatch):
    monkeypatch.setattr(agents_module, "load_knowledge_base", sample_knowledge)
    monkeypatch.setattr(agents_module, "load_playbooks", lambda: [sample_playbook()])
    client = TestClient(app)

    response = client.post(
        "/api/agent/chat",
        json={"message": "Run strategy council: agents talk to each other and create the best possible VSL campaign."},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["activeAgent"] == "orchestrator"
    assert 0 < payload["agentCouncil"]["averageScoreOutOf10"] <= 10
    assert "Strategy Council" in payload["answer"]
    assert payload["agentDecision"]["approvalRequired"] is True
