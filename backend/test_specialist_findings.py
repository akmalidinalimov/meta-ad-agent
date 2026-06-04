from backend.specialist_findings import creative_findings, placement_findings


def _knowledge_with_top_ads(top_ads):
    return {
        "analysis": {"topAds": top_ads, "summary": {"spend": 1000}},
        "raw": {"insights": {"base": []}},
    }


def test_creative_findings_surfaces_hook_and_hold_rate_in_headline():
    top_ads = [
        {
            "label": "VID-strong",
            "keys": {"ad_name": "VID-strong"},
            "spend": 200,
            "clicks": 600,
            "leads": 80,
            "purchases": 1,
            "hookRate": 34.0,
            "holdRate": 55.0,
        }
    ]
    finding = creative_findings(_knowledge_with_top_ads(top_ads))
    assert "hook 34%" in finding["headline"]
    assert finding["strongHook"] is not None


def test_creative_findings_flags_weak_hook_and_hold():
    top_ads = [
        {
            "label": "VID-good",
            "keys": {"ad_name": "VID-good"},
            "spend": 200,
            "clicks": 600,
            "leads": 80,
            "purchases": 1,
            "hookRate": 30.0,
            "holdRate": 55.0,
        },
        {
            "label": "VID-weak",
            "keys": {"ad_name": "VID-weak"},
            "spend": 120,
            "clicks": 300,
            "leads": 20,
            "purchases": 0,
            "hookRate": 12.0,
            "holdRate": 18.0,
        },
    ]
    finding = creative_findings(_knowledge_with_top_ads(top_ads))
    assert finding["weakHook"]["label"] == "VID-weak"
    assert finding["weakHold"]["label"] == "VID-weak"
    assert any("weak hook rate" in risk for risk in finding["risks"])
    assert any("weak hold rate" in risk for risk in finding["risks"])


def test_creative_findings_degrades_without_video_fields():
    top_ads = [
        {
            "label": "IMG-1",
            "keys": {"ad_name": "IMG-1"},
            "spend": 200,
            "clicks": 600,
            "leads": 80,
            "purchases": 0,
            "hookRate": None,
            "holdRate": None,
        }
    ]
    finding = creative_findings(_knowledge_with_top_ads(top_ads))
    assert finding["weakHook"] is None
    assert finding["strongHook"] is None
    assert "hook" not in finding["headline"].lower()


def _knowledge_with_placements(placements):
    return {
        "analysis": {"placements": placements, "summary": {"spend": 1000}},
        "raw": {"insights": {"base": []}},
    }


def test_placement_findings_flags_waste_when_margin_and_volume_significant():
    placements = [
        {"label": "instagram / reels", "spend": 300, "clicks": 800, "leads": 120, "cpl": 2.5},
        {"label": "facebook / feed", "spend": 250, "clicks": 700, "leads": 50, "cpl": 5.0},
    ]
    finding = placement_findings(_knowledge_with_placements(placements))
    assert finding["weak"] is not None
    assert any("Isolate" in risk for risk in finding["risks"])


def test_placement_findings_no_waste_when_margin_too_small():
    placements = [
        {"label": "instagram / reels", "spend": 300, "clicks": 800, "leads": 120, "cpl": 2.5},
        {"label": "instagram / stories", "spend": 250, "clicks": 700, "leads": 100, "cpl": 2.8},
    ]
    finding = placement_findings(_knowledge_with_placements(placements))
    assert finding["risks"] == [] or all("Isolate" not in r for r in finding["risks"])
    assert "no clear placement waste" in finding["headline"].lower() or finding["weak"] is None


def test_placement_findings_no_waste_when_weak_placement_insignificant():
    placements = [
        {"label": "instagram / reels", "spend": 300, "clicks": 800, "leads": 120, "cpl": 2.5},
        {"label": "facebook / feed", "spend": 8, "clicks": 12, "leads": 1, "cpl": 8.0},
    ]
    finding = placement_findings(_knowledge_with_placements(placements))
    # The high-CPL placement is below the significance floor, so it must not be called waste.
    assert all("Isolate" not in r for r in finding["risks"])
