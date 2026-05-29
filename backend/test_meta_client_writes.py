from backend.meta_client import normalize_write_payload


def test_normalize_write_payload_serializes_nested_meta_fields():
    payload = {
        "name": "Paused campaign",
        "status": "PAUSED",
        "special_ad_categories": [],
        "targeting": {
            "geo_locations": {"countries": ["UZ"]},
            "publisher_platforms": ["instagram"],
        },
        "optional": None,
    }

    normalized = normalize_write_payload(payload)

    assert normalized["name"] == "Paused campaign"
    assert normalized["status"] == "PAUSED"
    assert normalized["special_ad_categories"] == "[]"
    assert normalized["targeting"] == '{"geo_locations":{"countries":["UZ"]},"publisher_platforms":["instagram"]}'
    assert "optional" not in normalized
