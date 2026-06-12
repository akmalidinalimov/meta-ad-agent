from fastapi.testclient import TestClient

import backend.routers.agents as agents_module
from backend.app import app
from backend.campaign_analysis import (
    analyze_campaign,
    campaign_analysis_from_question,
    resolve_campaign,
)

CAMPAIGN_NAME = "DA - SHAHLOAI - VSL 2 - 26.04.2026 Y"
OTHER_NAME = "DA - BOSHQA - VSL 1 - 01.01.2026 X"


def _row(campaign_id, campaign_name, adset_id, adset_name, ad_id, ad_name, *, spend, clicks, leads, impressions=50000, platform="instagram", position="reels"):
    return {
        "campaign_id": campaign_id,
        "campaign_name": campaign_name,
        "adset_id": adset_id,
        "adset_name": adset_name,
        "ad_id": ad_id,
        "ad_name": ad_name,
        "spend": spend,
        "impressions": impressions,
        "clicks": clicks,
        "actions": [{"action_type": "lead", "value": str(leads)}],
        "publisher_platform": platform,
        "platform_position": position,
    }


def sample_campaign_knowledge():
    base = [
        _row("120111", CAMPAIGN_NAME, "as_ai", "TOF - UZB - 18-45 - ALL - AD+ [AI]", "ad_vid08", "VID - 08", spend=605.14, clicks=17912, leads=15676),
        _row("120111", CAMPAIGN_NAME, "as_biz", "TOF - UZB - 18-45 - ALL - AD+ [BUSINESS]", "ad_vid07", "VID - 07", spend=18.79, clicks=529, leads=476),
        _row("120111", CAMPAIGN_NAME, "as_biz", "TOF - UZB - 18-45 - ALL - AD+ [BUSINESS]", "ad_vid02", "VID - 02", spend=4.10, clicks=40, leads=12, platform="facebook", position="feed"),
        _row("120222", OTHER_NAME, "as_other", "Other ad set", "ad_other", "VID - 99", spend=300.0, clicks=5000, leads=1000),
    ]
    return {
        "raw": {
            "campaigns": [
                {"id": "120111", "name": CAMPAIGN_NAME},
                {"id": "120222", "name": OTHER_NAME},
            ],
            "ads": [
                {"id": "ad_vid08", "creative": {"id": "cr8", "name": "VID - 08", "thumbnail_url": "http://t/8.jpg", "video_id": "v8"}},
            ],
            "insights": {"base": base, "placement": base},
        },
        "analysis": {"summary": {"spend": 928, "leads": 17164, "purchases": 0}},
    }


def test_resolve_campaign_matches_full_name():
    kb = sample_campaign_knowledge()
    resolved = resolve_campaign(kb, f"Which audience should we scale from {CAMPAIGN_NAME} and why?")
    assert resolved == {"id": "120111", "name": CAMPAIGN_NAME}


def test_resolve_campaign_matches_distinctive_tokens():
    kb = sample_campaign_knowledge()
    resolved = resolve_campaign(kb, "which creative worked in SHAHLOAI VSL 2 26.04.2026?")
    assert resolved["id"] == "120111"


def test_resolve_campaign_disambiguates_between_campaigns():
    kb = sample_campaign_knowledge()
    resolved = resolve_campaign(kb, "show me BOSHQA VSL 1 01.01.2026 results")
    assert resolved["id"] == "120222"


def test_resolve_campaign_returns_none_without_a_named_campaign():
    kb = sample_campaign_knowledge()
    assert resolve_campaign(kb, "Which audience should we scale next?") is None
    assert resolve_campaign(None, CAMPAIGN_NAME) is None


def test_analyze_campaign_ranks_adsets_creatives_placements_with_real_metrics():
    kb = sample_campaign_knowledge()
    result = analyze_campaign(kb, {"id": "120111", "name": CAMPAIGN_NAME})

    assert result["hasData"] is True
    # Best ad set is the high-volume [AI] set; CPL ~ 605.14 / 15676.
    best = result["adSets"][0]
    assert "[AI]" in best["label"]
    assert round(best["cpl"], 4) == round(605.14 / 15676, 4)
    # Only the named campaign's rows are included (other campaign excluded).
    assert all("Other" not in item["label"] for item in result["adSets"])
    # Low-sample creative is flagged.
    vid02 = next(item for item in result["creatives"] if "VID - 02" in item["label"])
    assert vid02["lowSample"] is True
    # No purchases -> limitation noted.
    assert any("purchase" in note.lower() for note in result["limitations"])


def test_campaign_analysis_from_question_focuses_on_requested_dimension():
    kb = sample_campaign_knowledge()
    payload = campaign_analysis_from_question(kb, f"Which creative worked best in {CAMPAIGN_NAME}?", focus="creative")
    answer = payload["answer"]
    assert CAMPAIGN_NAME in answer
    assert "VID - 08" in answer
    # Creative section appears before the ad-set section when focus is creative.
    assert answer.index("Creatives ranked") < answer.index("Ad sets ranked")
    assert "$0.04" in answer  # CPL formatting for the best ad set / creative


def test_agent_chat_answers_with_campaign_specific_metrics(monkeypatch):
    monkeypatch.setattr(agents_module, "load_knowledge_base", lambda: sample_campaign_knowledge())
    client = TestClient(app)

    response = client.post(
        "/api/agent/chat",
        json={"message": f"Which audience should we scale from {CAMPAIGN_NAME} and why?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["activeAgent"] == "audience"
    assert CAMPAIGN_NAME in payload["answer"]
    assert "[AI]" in payload["answer"]
    assert "campaign_specific_analysis" in payload["sources"]
