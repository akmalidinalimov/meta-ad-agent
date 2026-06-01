from fastapi.testclient import TestClient

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
