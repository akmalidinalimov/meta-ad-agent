from backend.agent_orchestrator import (
    agent_registry,
    orchestrate_agent_chat,
    route_question,
)
from backend.test_strategy_generator import sample_knowledge, sample_playbook


def test_agent_registry_contains_required_specialists_with_safe_permissions():
    registry = agent_registry()

    assert {
        "orchestrator",
        "audit",
        "audience",
        "creative",
        "placement",
        "funnel",
        "monitoring",
        "experiment",
        "execution",
        "browser_operator",
    }.issubset(registry)
    assert registry["execution"]["canExecuteLiveChanges"] is False
    assert registry["browser_operator"]["canExecuteLiveChanges"] is False
    assert registry["execution"]["requiresApproval"] is True


def test_route_question_selects_specialist_without_live_execution():
    assert route_question("Which sub-agents are configured and can browser fallback be used?")["agentId"] == "orchestrator"
    assert route_question("Which creative and hook should we replicate?")["agentId"] == "creative"
    assert route_question("Should we target Tashkent or Uzbekistan broad?")["agentId"] == "audience"
    assert route_question("Set up a new campaign with $100 per segment")["agentId"] == "orchestrator"
    assert route_question("Go to browser and change the budget")["agentId"] == "execution"


def test_orchestrator_generates_campaign_plan_from_latest_playbook():
    response = orchestrate_agent_chat(
        "Create a campaign plan from the saved playbook",
        knowledge=sample_knowledge(),
        playbooks=[sample_playbook()],
    )

    assert response is not None
    assert response["activeAgent"] == "orchestrator"
    assert "approval-ready campaign plan" in response["answer"].lower()
    assert "$250" in response["answer"]
    assert "AI income" in response["answer"]
    assert "Business automation" in response["answer"]
    assert "I will not execute" in response["answer"]
    assert "strategy_generator" in response["sources"]


def test_orchestrator_asks_for_chat_variables_when_playbook_has_no_segments():
    response = orchestrate_agent_chat(
        "Set up my next campaign",
        knowledge=sample_knowledge(),
        playbooks=[{"id": "pb_empty", "name": "Empty", "segments": [], "rules": {}}],
    )

    assert response is not None
    assert response["activeAgent"] == "orchestrator"
    assert "tell me the segments" in response["answer"].lower()
    assert "budget" in response["answer"].lower()


def test_orchestrator_builds_campaign_plan_from_chat_brief_without_saved_playbook():
    response = orchestrate_agent_chat(
        "Create a campaign with 3 VSLs: earning money, business automation, content creators. Use $100 each and optimize for Telegram START.",
        knowledge=sample_knowledge(),
        playbooks=[{"id": "pb_empty", "name": "Empty", "segments": [], "rules": {}}],
    )

    assert response is not None
    assert response["activeAgent"] == "orchestrator"
    assert response["generatedPlaybook"]["id"].startswith("pb_chat_")
    assert len(response["generatedPlaybook"]["segments"]) == 3
    assert "chat_campaign_planner" in response["sources"]
    assert "Earning Money" in response["answer"]
    assert "I will not execute" in response["answer"]


def test_execution_agent_blocks_browser_fallback_until_specific_approval():
    response = orchestrate_agent_chat(
        "Use browser fallback and change my Meta budget now",
        knowledge=sample_knowledge(),
        playbooks=[sample_playbook()],
    )

    assert response is not None
    assert response["activeAgent"] == "execution"
    assert "specific approved action" in response["answer"].lower()
    assert "api first" in response["answer"].lower()
