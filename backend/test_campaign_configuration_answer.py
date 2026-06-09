"""Tests for the live campaign CONFIGURATION answer (objective/audience/interests/
placements/age/geo/custom-audiences/A-B/DCO) in campaign_specific_analysis."""

from __future__ import annotations

from backend.campaign_specific_analysis import (
    campaign_configuration_answer,
    format_custom_audiences,
    format_geo,
    format_interests,
    format_placements,
    is_configuration_question,
)

CAMPAIGN_NAME = "DA - SHAHLOAI - VSL 2 - 26.04.2026 Y"


def _campaigns():
    return [{"id": "cmp_1", "name": CAMPAIGN_NAME, "objective": "OUTCOME_LEADS", "buying_type": "AUCTION"}]


def _adsets():
    return [
        {
            "id": "as_1",
            "campaign_id": "cmp_1",
            "name": "TOF - UZB - [AI]",
            "optimization_goal": "OFFSITE_CONVERSIONS",
            "billing_event": "IMPRESSIONS",
            "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
            "is_dynamic_creative": True,
            "targeting": {
                "age_min": 18,
                "age_max": 45,
                "geo_locations": {"cities": [{"name": "Tashkent"}], "countries": ["UZ"]},
                "publisher_platforms": ["instagram"],
                "instagram_positions": ["reels", "story"],
                "flexible_spec": [{"interests": [{"name": "Entrepreneurship"}, {"name": "Marketing"}]}],
                "custom_audiences": [{"id": "ca_99"}],
            },
        }
    ]


def _adstudies():
    return [
        {
            "id": "study_1",
            "name": "VSL split test",
            "cells": {"data": [{"adsets": {"data": [{"id": "as_1", "campaign_id": "cmp_1"}]}}]},
        }
    ]


def test_is_configuration_question_truth_table():
    assert is_configuration_question("what audience and interests did the campaign use?")
    assert is_configuration_question("which placements are configured?")
    assert is_configuration_question("was A/B enabled on this campaign?")
    assert is_configuration_question("what objective and age range?")
    assert is_configuration_question("what custom audience and billing?")
    # Pure performance questions are not config questions.
    assert not is_configuration_question("which creative had the best CPL?")
    assert not is_configuration_question("how much did we spend yesterday?")


def test_configuration_answer_renders_full_config():
    answer = campaign_configuration_answer(
        f"what audience, interests, placements, and was A/B enabled on {CAMPAIGN_NAME}?",
        {},
        campaigns=_campaigns(),
        adsets=_adsets(),
        adstudies=_adstudies(),
        saved_audiences=[{"id": "ca_99", "name": "Past buyers"}],
        source="live",
    )
    assert answer is not None
    assert "Objective: OUTCOME_LEADS" in answer
    assert "Buying type: AUCTION" in answer
    assert "Age: 18-45" in answer
    assert "Tashkent" in answer
    assert "Entrepreneurship" in answer and "Marketing" in answer
    assert "instagram" in answer
    assert "Past buyers" in answer  # custom-audience id resolved to name
    assert "A/B test: enabled (VSL split test)" in answer
    assert "Dynamic creative (DCO): on" in answer
    # Live source -> no stale footer.
    assert "live Meta data was unavailable" not in answer


def test_configuration_answer_returns_none_for_performance_question():
    # No config trigger word -> None so the performance ranking path wins.
    assert (
        campaign_configuration_answer(
            f"which creative should we scale from {CAMPAIGN_NAME}?",
            {},
            campaigns=_campaigns(),
            adsets=_adsets(),
            source="live",
        )
        is None
    )


def test_configuration_answer_returns_none_without_config_data():
    # Config-shaped question but the named campaign has no ad sets and no A/B study ->
    # None, so the performance path still answers (keeps "audience" questions on perf).
    assert (
        campaign_configuration_answer(
            f"which audience did {CAMPAIGN_NAME} use?",
            {},
            campaigns=_campaigns(),
            adsets=[],
            adstudies=[],
            source="live",
        )
        is None
    )


def test_configuration_answer_applies_snapshot_footer():
    answer = campaign_configuration_answer(
        f"what placements did {CAMPAIGN_NAME} use?",
        {},
        campaigns=_campaigns(),
        adsets=_adsets(),
        adstudies=_adstudies(),
        source="snapshot",
    )
    assert answer is not None
    assert "live Meta data was unavailable" in answer


def test_format_custom_audiences_falls_back_to_id():
    targeting = {"custom_audiences": [{"id": "ca_unknown"}]}
    assert format_custom_audiences(targeting, {}) == "ca_unknown"
    assert format_custom_audiences(targeting, {"ca_unknown": "VIPs"}) == "VIPs"


def test_format_interests_truncates_long_lists():
    interests = [{"name": f"int{i}"} for i in range(20)]
    targeting = {"flexible_spec": [{"interests": interests}]}
    rendered = format_interests(targeting, 5)
    assert "int0" in rendered
    assert "+15 more" in rendered


def test_format_geo_and_placements_handle_empty():
    assert format_geo({}) is None
    assert format_placements({}) is None
