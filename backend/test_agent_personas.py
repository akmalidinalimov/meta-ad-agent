import asyncio

from backend.agent_personas import HOUSE_STRATEGY, specialist_system_prompt
from backend.llm_reasoner import answer_is_grounded, generate_specialist_answer


def test_specialist_prompt_includes_role_and_house_strategy():
    prompt = specialist_system_prompt("creative")
    assert prompt is not None
    assert "creative strategist" in prompt.lower()
    # House strategy / account context must be injected so the agent reasons like
    # this account's buyer, not a generic Meta analyst.
    assert HOUSE_STRATEGY.split("\n", 1)[0] in prompt
    assert "Telegram START" in prompt
    # The presentation directive is appended so chat answers render readably.
    assert "Output format" in prompt


def test_specialist_prompt_none_for_non_persona_agents():
    # Orchestrator/execution paths are handled deterministically, not via persona.
    assert specialist_system_prompt("execution") is None
    assert specialist_system_prompt("orchestrator") is None
    assert specialist_system_prompt("not_a_real_agent") is None


def test_answer_is_grounded_accepts_numbers_present_in_context():
    context = '{"summary": {"spend": 1240, "cpl": 0.04, "leads": 31000}}'
    answer = "Spend was 1240 and CPL is 0.04 across 31000 leads."
    assert answer_is_grounded(answer, context) is True


def test_answer_is_grounded_rejects_fabricated_numbers():
    context = '{"summary": {"spend": 1240, "leads": 31000}}'
    # 4.7x ROAS and 980 purchases are not in the context — a hallucination.
    answer = "ROAS was 4.7x with 980 purchases."
    assert answer_is_grounded(answer, context) is False


def test_answer_is_grounded_ignores_small_incidental_numbers():
    context = '{"summary": {"spend": 1240}}'
    answer = "In the first 3 days, focus on the top 5 ad sets; spend was 1240."
    assert answer_is_grounded(answer, context) is True


def test_generate_specialist_answer_returns_none_without_api_key(monkeypatch):
    # The autouse conftest fixture already clears the key; assert the deterministic
    # fallback contract holds (caller will use its template).
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = asyncio.run(
        generate_specialist_answer("rank creatives", {"summary": {}}, system_prompt="x")
    )
    assert result is None
