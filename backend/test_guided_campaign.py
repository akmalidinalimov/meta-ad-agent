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


# ---------------------------------------------------------------------------
# Pending store: guided blob persistence
# ---------------------------------------------------------------------------


def test_pending_persists_guided_blob(tmp_path):
    from backend.pending_context_store import set_pending, get_pending
    set_pending("tg:1", {"kind": "guided_create", "guided": {"step": "audience", "selectedCreatives": ["cr_1"]}}, storage_dir=tmp_path)
    got = get_pending("tg:1", storage_dir=tmp_path)
    assert got["kind"] == "guided_create"
    assert got["guided"]["selectedCreatives"] == ["cr_1"]


# ---------------------------------------------------------------------------
# Guided campaign state machine
# ---------------------------------------------------------------------------

from backend import guided_campaign


def test_start_sets_audience_step_and_returns_question(tmp_path):
    out = guided_campaign.start("tg:1", storage_dir=tmp_path)
    from backend.pending_context_store import get_pending
    p = get_pending("tg:1", storage_dir=tmp_path)
    assert p["kind"] == "guided_create"
    assert p["guided"]["step"] == "audience"
    assert "audience" in out["text"].lower()
    cbs = [b["callback_data"] for row in out["reply_markup"]["inline_keyboard"] for b in row]
    assert {"gcreate:aud:proven", "gcreate:aud:new", "gcreate:aud:input"} <= set(cbs)


def test_audience_choice_input_prompts_for_text(tmp_path):
    guided_campaign.start("tg:1", storage_dir=tmp_path)
    out = guided_campaign.handle_audience_choice("tg:1", "input", storage_dir=tmp_path)
    from backend.pending_context_store import get_pending
    assert get_pending("tg:1", storage_dir=tmp_path)["guided"]["step"] == "audience_text"
    assert "audience" in out["text"].lower()


def test_audience_choice_proven_advances_to_creatives(tmp_path):
    guided_campaign.start("tg:1", storage_dir=tmp_path)
    out = guided_campaign.handle_audience_choice("tg:1", "proven", storage_dir=tmp_path)
    from backend.pending_context_store import get_pending
    p = get_pending("tg:1", storage_dir=tmp_path)
    assert p["guided"]["step"] == "creatives"
    assert p["guided"]["audienceChoice"] == "proven"
    assert out["next"] == "render_creatives"


# ---------------------------------------------------------------------------
# Task 3: creative pool + tap-to-toggle selection
# ---------------------------------------------------------------------------


def test_creative_toggle_adds_then_removes(tmp_path):
    guided_campaign.start("tg:1", storage_dir=tmp_path)
    guided_campaign.handle_audience_choice("tg:1", "proven", storage_dir=tmp_path)
    sel1 = guided_campaign.handle_creative_toggle("tg:1", "cr_1", storage_dir=tmp_path)
    assert sel1 == ["cr_1"]
    sel2 = guided_campaign.handle_creative_toggle("tg:1", "cr_2", storage_dir=tmp_path)
    assert set(sel2) == {"cr_1", "cr_2"}
    sel3 = guided_campaign.handle_creative_toggle("tg:1", "cr_1", storage_dir=tmp_path)
    assert sel3 == ["cr_2"]


def test_top_creatives_for_selection_reads_creative_id():
    knowledge = {"analysis": {"topAds": [
        {"name": "Ad A", "creative": {"id": "cr_1", "thumbnail_url": "t1", "video_id": "v1"}},
        {"name": "Ad B", "creative": {"id": "cr_2", "image_url": "i2"}},
    ]}}
    rows = guided_campaign.top_creatives_for_selection(knowledge, limit=5)
    # The selection id MUST be the creative id (matches the creative_ids filter), not an ad id.
    assert [r["id"] for r in rows] == ["cr_1", "cr_2"]
    assert rows[0]["videoId"] == "v1"
    assert rows[1]["thumb"] == "i2"
    assert {"id", "name", "thumb", "videoId"} <= set(rows[0].keys())


def test_creative_toggle_label_flips():
    assert guided_campaign.creative_toggle_label("cr_1", []) == "➕ Select"
    assert guided_campaign.creative_toggle_label("cr_1", ["cr_1"]) == "✅ Selected"
