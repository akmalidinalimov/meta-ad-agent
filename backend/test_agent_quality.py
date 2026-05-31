from backend.agent_quality import evaluate_agent_response


def test_evaluate_agent_response_marks_complete_answer_usable():
    result = evaluate_agent_response(
        {
            "activeAgent": "orchestrator",
            "routeReason": "Campaign planning request.",
            "answer": "Use three segments and require approval before execution.",
            "sources": ["strategy_generator"],
            "suggestedQuestions": ["Turn this into approval requests."],
            "agentHandoffs": [
                {
                    "fromAgent": "orchestrator",
                    "toAgent": "audience",
                    "reason": "Validate targeting.",
                    "inputsNeeded": ["playbook"],
                    "expectedOutput": "Audience ranking",
                    "confidence": "high",
                }
            ],
        }
    )

    assert result["status"] == "usable"
    assert result["score"] == 100
    assert result["issues"] == []


def test_evaluate_agent_response_flags_missing_sources_and_next_steps():
    result = evaluate_agent_response(
        {
            "activeAgent": "creative",
            "routeReason": "Creative question.",
            "answer": "Try new hooks.",
            "sources": [],
            "suggestedQuestions": [],
            "agentHandoffs": [],
        }
    )

    assert result["status"] == "needs_refinement"
    assert result["score"] < 95
    assert "missing_sources" in result["issues"]
    assert "missing_next_steps" in result["issues"]


def test_evaluate_agent_response_blocks_empty_answer():
    result = evaluate_agent_response(
        {
            "activeAgent": "audit",
            "routeReason": "Historical audit.",
            "answer": "",
            "sources": ["knowledge_base"],
            "suggestedQuestions": ["What should we test?"],
        }
    )

    assert result["status"] == "blocked"
    assert "missing_answer" in result["issues"]
