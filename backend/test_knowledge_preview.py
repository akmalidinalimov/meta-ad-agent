from backend.dashboard_service import knowledge_chat_preview


def test_knowledge_chat_preview_uses_snapshot_days_instead_of_hardcoded_90_day_label():
    preview = knowledge_chat_preview(
        {
            "snapshot": {"days": 180},
            "analysis": {"summary": {}, "rawCounts": {}},
            "raw": {},
        }
    )

    assert preview["role"] == "canonical_meta_ads_knowledge_base"
    assert preview["analysisWindowDays"] == 180
    assert "180-day" in preview["instructions"][0]
    assert "90-day" not in " ".join(preview["instructions"])
