from backend.settings_audit import build_settings_audit


def test_settings_audit_extracts_advantage_audience_and_placement_risk():
    raw = {
        "campaigns": [
            {
                "id": "campaign_1",
                "name": "Income VSL",
                "objective": "OUTCOME_LEADS",
                "daily_budget": "10000",
                "effective_status": "ACTIVE",
            }
        ],
        "adsets": [
            {
                "id": "adset_1",
                "campaign_id": "campaign_1",
                "name": "UZ broad advantage",
                "optimization_goal": "LEAD_GENERATION",
                "daily_budget": "5000",
                "targeting": {
                    "age_min": 18,
                    "age_max": 45,
                    "genders": [0],
                    "geo_locations": {"countries": ["UZ"]},
                    "targeting_automation": {"advantage_audience": 1},
                    "publisher_platforms": ["facebook", "instagram"],
                    "instagram_positions": ["stream", "story", "reels"],
                    "facebook_positions": ["feed", "facebook_reels"],
                    "flexible_spec": [{"interests": [{"name": "Marketing services"}]}],
                },
            }
        ],
        "ads": [{"id": "ad_1", "adset_id": "adset_1", "campaign_id": "campaign_1", "status": "ACTIVE"}],
    }

    audit = build_settings_audit(raw)

    assert audit["summary"]["campaigns"] == 1
    assert audit["summary"]["adsets"] == 1
    assert audit["summary"]["advantageAudienceAdsets"] == 1
    assert audit["adsets"][0]["advantageAudience"] is True
    assert audit["adsets"][0]["locations"] == ["UZ"]
    assert "facebook_feed" in audit["adsets"][0]["placements"]
    assert any(item["severity"] == "warning" for item in audit["risks"])


def test_settings_audit_flags_broad_country_as_configurable_not_bad():
    raw = {
        "campaigns": [],
        "adsets": [
            {
                "id": "adset_uz",
                "name": "UZ country",
                "targeting": {
                    "age_min": 18,
                    "age_max": 65,
                    "geo_locations": {"countries": ["UZ"]},
                    "publisher_platforms": ["instagram"],
                    "instagram_positions": ["reels", "story"],
                },
            }
        ],
        "ads": [],
    }

    audit = build_settings_audit(raw)

    assert audit["adsets"][0]["geoStrategy"] == "country"
    assert audit["adsets"][0]["recommendedUse"] == "Good baseline control"
