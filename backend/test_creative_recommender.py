import asyncio

import backend.creative_recommender as cr
from backend.creative_recommender import (
    build_new_angle_briefs,
    build_recommended_creatives,
    generate_creative_angle_briefs,
)


def _ad(name, quality, *, hook=None, hold=None, purchases=0, leads=0, fatigued=False):
    return {
        "label": name,
        "keys": {"ad_id": f"ad_{name}", "ad_name": name},
        "qualityScore": quality,
        "hookRate": hook,
        "holdRate": hold,
        "purchases": purchases,
        "leads": leads,
        "fatigued": fatigued,
        "creative": {"id": f"cr_{name}", "name": name, "objectType": "VIDEO"},
    }


def _analysis_with_ads(ads):
    return {
        "topAds": ads,
        "audience": {"interests": [{"label": "Artificial intelligence"}]},
    }


def test_build_recommended_creatives_selects_best_per_segment():
    analysis = _analysis_with_ads(
        [
            _ad("A", 90, hook=34, hold=55, purchases=2, leads=100),
            _ad("B", 70, hook=26, hold=45, leads=60),
            _ad("C", 50, hook=20, hold=40, leads=20),
            _ad("D", 40, hook=15, hold=35, leads=10),
        ]
    )
    blocks = build_recommended_creatives(analysis, ["Seg1", "Seg2"], per_segment=2)

    assert [b["segment"] for b in blocks] == ["Seg1", "Seg2"]
    reuse = blocks[0]["reuseExisting"]
    assert len(reuse) == 2
    # Sorted by quality desc -> A then B.
    assert [r["name"] for r in reuse] == ["A", "B"]
    assert reuse[0]["creativeId"] == "cr_A"
    assert reuse[0]["format"] == "video"
    assert reuse[0]["qualityScore"] == 90
    assert "Reuse A" in reuse[0]["rationale"]
    # Both segments get the same deterministic briefs.
    assert blocks[0]["newAngleBriefs"] == blocks[1]["newAngleBriefs"]


def test_build_recommended_creatives_excludes_fatigued():
    analysis = _analysis_with_ads(
        [
            _ad("Fresh", 80, hook=30, hold=55, leads=80),
            _ad("FlaggedFatigue", 95, hook=33, hold=55, leads=120, fatigued=True),
            _ad("LowHold", 92, hook=33, hold=10, leads=120),  # hold below floor -> fatigued
        ]
    )
    blocks = build_recommended_creatives(analysis, ["Seg1"], per_segment=5)
    names = [r["name"] for r in blocks[0]["reuseExisting"]]
    assert names == ["Fresh"]
    assert "FlaggedFatigue" not in names
    assert "LowHold" not in names


def test_build_recommended_creatives_has_deterministic_briefs():
    analysis = _analysis_with_ads([_ad("A", 80, hook=30, hold=55, leads=80)])
    blocks = build_recommended_creatives(analysis, ["Seg1"])
    briefs = blocks[0]["newAngleBriefs"]
    assert 2 <= len(briefs) <= 3
    angles = {b["angle"] for b in briefs}
    assert "Outcome proof" in angles
    assert "Objection-handling" in angles
    for brief in briefs:
        assert set(brief) >= {"angle", "hook", "format", "whyItMightWork"}


def test_build_recommended_creatives_empty_analysis_safe():
    assert build_recommended_creatives({}, ["Seg1"]) and all(
        block["reuseExisting"] == [] for block in build_recommended_creatives({}, ["Seg1"])
    )
    # No segments -> empty list.
    assert build_recommended_creatives(_analysis_with_ads([_ad("A", 80)]), []) == []
    assert build_recommended_creatives(None, None) == []
    # Briefs still produced even with no creatives.
    block = build_recommended_creatives({}, ["Seg1"])[0]
    assert len(block["newAngleBriefs"]) >= 2


def test_generate_creative_angle_briefs_falls_back_when_reason_none(monkeypatch):
    async def _none(*args, **kwargs):
        return None

    monkeypatch.setattr(cr, "reason", _none)
    analysis = _analysis_with_ads([_ad("A", 80, hook=30, hold=55, leads=80)])
    result = asyncio.run(generate_creative_angle_briefs(analysis, ["Seg1"]))
    assert result == build_new_angle_briefs(analysis)


def test_generate_creative_angle_briefs_parses_valid_json(monkeypatch):
    payload = (
        "```json\n"
        '[{"angle": "Speed", "hook": "Fast result", "format": "video", '
        '"whyItMightWork": "tempo"}]\n'
        "```"
    )

    async def _json(*args, **kwargs):
        return payload

    monkeypatch.setattr(cr, "reason", _json)
    result = asyncio.run(generate_creative_angle_briefs({}, ["Seg1"]))
    assert result == [
        {
            "angle": "Speed",
            "hook": "Fast result",
            "format": "video",
            "whyItMightWork": "tempo",
        }
    ]


def test_generate_creative_angle_briefs_falls_back_on_unparseable(monkeypatch):
    async def _garbage(*args, **kwargs):
        return "not json at all"

    monkeypatch.setattr(cr, "reason", _garbage)
    analysis = _analysis_with_ads([_ad("A", 80, hook=30, hold=55, leads=80)])
    result = asyncio.run(generate_creative_angle_briefs(analysis, ["Seg1"]))
    assert result == build_new_angle_briefs(analysis)
