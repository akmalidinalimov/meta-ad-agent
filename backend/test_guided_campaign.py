"""Guided campaign creation — builder overrides + flow state machine."""

from backend.meta_execution import build_campaign_creation_approval


def _playbook():
    return {
        "segments": [
            {"name": "Business education", "interests": ["Business education"],
             "ageRange": "25-44", "gender": "all", "locations": ["Tashkent"], "dailyBudget": 100},
        ],
    }


def _knowledge_with_creatives():
    # extract_top_creatives reads ad.get("creative", {}).get("id"), so topAds items
    # must carry a nested "creative" dict with an "id" field. The pool items produced
    # by extract_top_creatives use "creativeId" as the key.
    return {
        "analysis": {
            "topAds": [
                {"creative": {"id": "cr_1", "name": "Winner A"}, "qualityScore": 90, "purchases": 5},
                {"creative": {"id": "cr_2", "name": "Winner B"}, "qualityScore": 80, "purchases": 3},
                {"creative": {"id": "cr_3", "name": "Winner C"}, "qualityScore": 70, "purchases": 1},
            ]
        }
    }


def _ad_creative_ids(approval):
    ids = []
    for adset in (approval.get("after") or {}).get("adsets", []):
        for ad in adset.get("ads") or []:
            ids.append(str(ad.get("creativeId")))
    return ids


def test_creative_ids_filter_limits_ads_to_selection():
    approval = build_campaign_creation_approval(
        _playbook(), account_id="act_1", knowledge=_knowledge_with_creatives(),
        creatives_limit=5, creative_ids=["cr_3"],
    )
    assert _ad_creative_ids(approval) == ["cr_3"]


def test_no_creative_ids_keeps_default_top_n():
    approval = build_campaign_creation_approval(
        _playbook(), account_id="act_1", knowledge=_knowledge_with_creatives(),
        creatives_limit=2,
    )
    assert _ad_creative_ids(approval) == ["cr_1", "cr_2"]


# ---------------------------------------------------------------------------
# Audience override tests
# ---------------------------------------------------------------------------

from backend.opportunity_finder import build_autonomous_campaign


def _knowledge_full():
    return {
        "analysis": {
            "audience": {"interests": [
                {"label": "Business education", "qualityScore": 90, "telegramSubscribers": 4},
                {"label": "E-commerce", "qualityScore": 70},
            ], "ageGender": [], "regions": []},
            "topAds": _knowledge_with_creatives()["analysis"]["topAds"],
            "summary": {},
        }
    }


def test_audience_override_builds_those_audiences():
    # _segment_from_audience reads audience.get("label") for the segment name,
    # so the override dict must carry "label" (not "name") for the assertion to pass.
    approval = build_autonomous_campaign(
        _knowledge_full(), [], account_id="act_1", n_creatives=5,
        audience_override=[{"label": "Crypto traders", "interests": ["Crypto"],
                            "ageRange": "25-34", "gender": "all", "locations": ["Tashkent"]}],
    )
    names = [a.get("name", "") for a in (approval.get("after") or {}).get("adsets", [])]
    assert any("Crypto traders" in n for n in names)


def test_default_path_unchanged_when_no_overrides():
    approval = build_autonomous_campaign(_knowledge_full(), [], account_id="act_1", n_creatives=5)
    assert approval is not None
    assert (approval.get("after") or {}).get("adsets")
