import pytest

from backend.agent_orchestrator import (
    agent_registry,
    build_agent_decision,
    is_campaign_creation_request,
    orchestrate_agent_chat,
    route_question,
)
from backend.test_strategy_generator import sample_knowledge, sample_playbook


CAMPAIGN_NAME = "DA - SHAHLOAI - VSL 2 - 26.04.2026 Y"


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
        "meta_ai_advisor",
        "meta_ai_strategist",
        "execution",
        "browser_operator",
    }.issubset(registry)
    assert registry["meta_ai_advisor"]["canExecuteLiveChanges"] is False
    assert registry["meta_ai_strategist"]["canExecuteLiveChanges"] is False
    assert registry["meta_ai_advisor"]["requiresApproval"] is False
    assert registry["meta_ai_strategist"]["requiresApproval"] is False
    assert registry["execution"]["canExecuteLiveChanges"] is False
    assert registry["browser_operator"]["canExecuteLiveChanges"] is False
    assert registry["execution"]["requiresApproval"] is True


def test_route_question_selects_specialist_without_live_execution():
    assert route_question("Which sub-agents are configured and can browser fallback be used?")["agentId"] == "orchestrator"
    assert route_question("Which creative and hook should we replicate?")["agentId"] == "creative"
    assert route_question("Should we target Tashkent or Uzbekistan broad?")["agentId"] == "audience"
    assert route_question("Set up a new campaign with $100 per segment")["agentId"] == "orchestrator"
    assert route_question("Go to browser and change the budget")["agentId"] == "execution"
    assert route_question("Ask Meta AI to analyze this ad set and compare it with our funnel data")["agentId"] == "meta_ai_advisor"
    assert route_question("Create a Meta AI strategy from the Analyze answers")["agentId"] == "meta_ai_strategist"


@pytest.mark.parametrize(
    "question, expected_agent",
    [
        # Analysis questions about a named campaign must hit the analysis specialists,
        # even though the campaign name itself contains the token "VSL".
        (f"Which audience should we scale from {CAMPAIGN_NAME} and why?", "audience"),
        (f"Which creative worked best in {CAMPAIGN_NAME}?", "creative"),
        (f"Rank the creatives by leads and CPL for {CAMPAIGN_NAME}", "creative"),
        (f"Which placement performed best for {CAMPAIGN_NAME}?", "placement"),
        ("Which interests and age range converted cheapest?", "audience"),
        ("Should we trust Facebook placements or stay on Instagram Reels?", "placement"),
        # Creation requests route to the campaign builder (orchestrator) ...
        ("Create a campaign with $100 per segment optimized for Telegram START", "orchestrator"),
        ("Build a new campaign plan from the VSL 2 winners", "orchestrator"),
        ("Set up my next campaign", "orchestrator"),
        # ... including paused-draft creation, which must NOT be read as a pause action.
        ("Create a paused campaign plan - DO NOT PUBLISH - DRAFT", "orchestrator"),
        ("Prepare a paused campaign and paused ad sets only", "orchestrator"),
        # Object-level edits route to the approval-gated execution agent.
        ("Rename campaign 120123 to Business Automation VSL", "execution"),
        ("Pause ad set 987654321 now", "execution"),
        ("Go to the browser and change the budget", "execution"),
    ],
)
def test_route_question_distinguishes_analysis_creation_and_execution(question, expected_agent):
    assert route_question(question)["agentId"] == expected_agent


def test_campaign_name_token_vsl_is_not_treated_as_creation_intent():
    assert is_campaign_creation_request(f"Which audience should we scale from {CAMPAIGN_NAME}?") is False
    assert is_campaign_creation_request("Create a paused campaign plan - DO NOT PUBLISH") is True


def test_named_campaign_audience_question_does_not_generate_plan_or_execution():
    response = orchestrate_agent_chat(
        f"Which audience should we scale from {CAMPAIGN_NAME} and why?",
        knowledge=sample_knowledge(),
        playbooks=[sample_playbook()],
    )

    # The analysis specialists are answered downstream (LLM/knowledge base), so the
    # orchestrator must not hijack the turn with a planning or execution response.
    assert response is None


def test_paused_campaign_plan_request_builds_plan_not_execution_action():
    response = orchestrate_agent_chat(
        "Create a paused campaign plan with $100 per segment - DO NOT PUBLISH - DRAFT",
        knowledge=sample_knowledge(),
        playbooks=[sample_playbook()],
    )

    assert response is not None
    assert response["activeAgent"] == "orchestrator"
    assert "generatedApprovalRequest" not in response
    assert "I will not execute" in response["answer"]

def test_route_question_keeps_campaign_specific_analysis_with_specialist():
    assert (
        route_question("Which audience should we scale from DA - SHAHLOAI - VSL 2 - 26.04.2026 Y and why?")["agentId"]
        == "audience"
    )
    assert (
        route_question("Rank the creative videos from DA - SHAHLOAI - VSL 2 - 26.04.2026 Y")["agentId"]
        == "creative"
    )
    assert (
        route_question("Which placements worked for DA - SHAHLOAI - VSL 2 - 26.04.2026 Y?")["agentId"]
        == "placement"
    )


def test_route_question_does_not_match_age_inside_landing_page():
    assert (
        route_question("Diagnose whether we lose people before landing page, Telegram START, form, or CRM purchase.")["agentId"]
        == "funnel"
    )


def test_routes_to_new_specialist_agents():
    assert route_question("Is our pixel/CAPI attribution healthy and are leads double-counted?")["agentId"] == "measurement"
    assert route_question("Are we under-pacing budget and should this be CBO or ABO?")["agentId"] == "budget_pacing"
    assert route_question("How do we fix the landing page message match and page speed?")["agentId"] == "landing_cro"


def test_new_specialist_agents_registered_with_safe_permissions():
    registry = agent_registry()
    for agent_id in ["measurement", "budget_pacing", "landing_cro"]:
        assert agent_id in registry
        assert registry[agent_id]["canExecuteLiveChanges"] is False


def test_confidence_is_evidence_derived_not_field_presence():
    # A thin single-agent response (sources + next steps but no confident handoffs)
    # should be moderate, NOT a 95 stamped purely for having non-empty fields.
    thin = build_agent_decision(
        {"agentId": "audit", "reason": "Default audit."},
        {"sources": ["knowledge_base"], "suggestedQuestions": ["What next?"], "agentHandoffs": []},
    )
    assert thin["confidenceScore"] < 80
    assert thin["confidenceBasis"]

    # An execution path with no cited policy/sources should be penalized.
    weak_exec = build_agent_decision(
        {"agentId": "execution", "reason": "Execution intent."},
        {"sources": [], "suggestedQuestions": [], "agentHandoffs": []},
    )
    assert weak_exec["confidenceScore"] <= thin["confidenceScore"]


def test_orchestrator_handles_multi_specialist_strategy_questions_with_decision_trace():
    response = orchestrate_agent_chat(
        "Analyze the best audience, creatives, placements, funnel quality, and experiments for the next campaign",
        knowledge=sample_knowledge(),
        playbooks=[sample_playbook()],
    )

    assert response is not None
    assert response["activeAgent"] == "orchestrator"
    assert response["agentDecision"]["primaryAgent"] == "orchestrator"
    assert response["agentDecision"]["confidenceScore"] >= 95
    assert set(response["agentDecision"]["involvedAgents"]) >= {
        "audience",
        "creative",
        "placement",
        "funnel",
        "experiment",
    }
    assert response["agentDecision"]["approvalRequired"] is True
    assert response["quality"]["status"] == "usable"


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
    assert {handoff["toAgent"] for handoff in response["agentHandoffs"]} >= {
        "audience",
        "creative",
        "placement",
        "funnel",
        "experiment",
    }


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
    assert response["agentHandoffs"][0]["toAgent"] == "browser_operator"
    assert response["agentHandoffs"][0]["confidence"] == "blocked_until_approval"


def test_execution_agent_creates_approval_ready_plan_from_natural_language_action():
    response = orchestrate_agent_chat(
        "Rename campaign 120123 to Business Automation VSL - Tashkent",
        knowledge=sample_knowledge(),
        playbooks=[sample_playbook()],
    )

    assert response is not None
    assert response["activeAgent"] == "execution"
    assert response["generatedMetaActionPlan"]["intent"] == "rename"
    assert response["generatedMetaActionPlan"]["target"]["id"] == "120123"
    assert response["generatedApprovalRequest"]["actionType"] == "rename_meta_object"
    assert response["generatedApprovalRequest"]["status"] == "needs_review"
    assert "approval" in response["answer"].lower()


def test_execution_agent_asks_clarifying_question_for_ambiguous_action():
    response = orchestrate_agent_chat(
        "Pause the weak ad set",
        knowledge=sample_knowledge(),
        playbooks=[sample_playbook()],
    )

    assert response is not None
    assert response["activeAgent"] == "execution"
    assert response["generatedMetaActionPlan"]["needsClarification"] is True
    assert "which target object id" in response["answer"].lower()
    assert "generatedApprovalRequest" not in response


def test_meta_ai_advisor_explains_browser_capture_workflow():
    response = orchestrate_agent_chat(
        "Use Meta AI Analyze for this campaign and tell me whether to trust it",
        knowledge=sample_knowledge(),
        playbooks=[sample_playbook()],
    )

    assert response is not None
    assert response["activeAgent"] == "meta_ai_advisor"
    assert "read-only" in response["answer"].lower()
    assert "orchestrator" in response["answer"].lower()
    assert "telegram" in response["answer"].lower()
    assert "Meta AI" in response["answer"]


def test_meta_ai_strategist_explains_meta_side_strategy_scope():
    response = orchestrate_agent_chat(
        "Use the Meta AI captures to create a Meta-side strategy for ad sets, audiences, and creatives",
        knowledge=sample_knowledge(),
        playbooks=[sample_playbook()],
    )

    assert response is not None
    assert response["activeAgent"] == "meta_ai_strategist"
    assert "meta-side strategy" in response["answer"].lower()
    assert "orchestrator" in response["answer"].lower()
    assert "not the final business strategy" in response["answer"].lower()
    assert {handoff["toAgent"] for handoff in response["agentHandoffs"]} >= {
        "audience",
        "creative",
        "funnel",
        "experiment",
    }


def test_agent_handoffs_are_structured_for_meta_ai_advisor():
    response = orchestrate_agent_chat(
        "Use Meta AI Analyze for this campaign and ask what audiences and creatives worked",
        knowledge=sample_knowledge(),
        playbooks=[sample_playbook()],
    )

    assert response is not None
    assert response["activeAgent"] == "meta_ai_advisor"
    assert response["agentHandoffs"]
    assert response["agentHandoffs"][0].keys() >= {
        "fromAgent",
        "toAgent",
        "reason",
        "inputsNeeded",
        "expectedOutput",
        "confidence",
    }
    assert response["quality"]["status"] == "usable"
    assert response["quality"]["score"] >= 95
