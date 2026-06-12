from datetime import datetime, timedelta, timezone

from backend.campaign_manage import (
    agent_created_index,
    build_manage_approval,
    detect_manage_intent,
    format_manage_answer,
    resolve_target_campaigns,
)


def _iso(days_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def test_detect_manage_intent_truth_table():
    # Archive (delete/remove/clean up/get rid of) -> archive.
    assert detect_manage_intent("delete all campaigns created past a week")["action"] == "archive"
    assert detect_manage_intent("remove the old test campaigns")["action"] == "archive"
    assert detect_manage_intent("clean up the campaigns you created")["action"] == "archive"
    assert detect_manage_intent("get rid of the idle campaigns")["action"] == "archive"
    assert detect_manage_intent("archive the stale campaigns")["action"] == "archive"

    # Pause (pause/turn off/stop/disable) -> pause.
    assert detect_manage_intent("pause the idle ones you created")["action"] == "pause"
    assert detect_manage_intent("turn off all the test campaigns")["action"] == "pause"
    assert detect_manage_intent("stop the campaigns you made last week")["action"] == "pause"

    # Creation / single-target tweaks -> None.
    assert detect_manage_intent("create a campaign for income VSL") is None
    assert detect_manage_intent("launch a new campaign") is None
    assert detect_manage_intent("rename campaign X to Business Automation") is None
    # Verb but no collection signal -> None.
    assert detect_manage_intent("pause it") is None


def test_agent_created_index_collects_campaign_ids_and_timestamps(monkeypatch):
    import backend.approval_store as approval_store

    monkeypatch.setattr(
        approval_store,
        "list_approval_requests",
        lambda: [
            {
                "actionType": "create_paused_campaign_structure",
                "createdAt": "2026-01-01T00:00:00+00:00",
                "executionLog": [
                    {
                        "executedAt": "2026-02-01T00:00:00+00:00",
                        "result": {
                            "created": [
                                {"level": "campaign", "id": "cmp_a", "name": "A - DRAFT"},
                                {"level": "adset", "id": "as_a"},
                            ]
                        },
                    }
                ],
            },
            {
                # No executedAt on the entry -> falls back to approval createdAt.
                "actionType": "create_paused_campaign_structure",
                "createdAt": "2026-03-01T00:00:00+00:00",
                "executionLog": [{"result": {"created": [{"level": "campaign", "id": "cmp_b"}]}}],
            },
            {"actionType": "rename_meta_object", "executionLog": []},
        ],
    )

    ids, created_at = agent_created_index()
    assert ids == {"cmp_a", "cmp_b"}
    assert created_at["cmp_a"] == "2026-02-01T00:00:00+00:00"
    assert created_at["cmp_b"] == "2026-03-01T00:00:00+00:00"


def test_resolve_agent_created_filter():
    campaigns = [
        {"id": "cmp_a", "name": "A", "effective_status": "PAUSED"},
        {"id": "cmp_b", "name": "B - DRAFT", "effective_status": "PAUSED"},
        {"id": "cmp_x", "name": "Not agent", "effective_status": "PAUSED"},
    ]
    selected, labels = resolve_target_campaigns(
        "pause the campaigns you created",
        campaigns,
        agent_ids={"cmp_a"},
        agent_created_at={},
    )
    ids = {c["id"] for c in selected}
    assert ids == {"cmp_a", "cmp_b"}  # cmp_b matched by DRAFT suffix
    assert any("created by the agent" in label for label in labels)


def test_resolve_idle_filter_excludes_active():
    campaigns = [
        {"id": "cmp_active", "name": "Running", "effective_status": "ACTIVE"},
        {"id": "cmp_idle", "name": "Idle", "effective_status": "PAUSED"},
    ]
    selected, labels = resolve_target_campaigns(
        "pause the idle campaigns",
        campaigns,
        agent_ids=set(),
        agent_created_at={},
    )
    assert {c["id"] for c in selected} == {"cmp_idle"}
    assert any("idle" in label for label in labels)


def test_resolve_recency_uses_agent_created_at():
    campaigns = [
        {"id": "cmp_old", "name": "Old", "effective_status": "PAUSED", "start_time": _iso(2)},
        {"id": "cmp_new", "name": "New", "effective_status": "PAUSED", "start_time": _iso(1)},
        {"id": "cmp_no_ts", "name": "NoTs", "effective_status": "PAUSED"},
    ]
    selected, labels = resolve_target_campaigns(
        "archive campaigns created over a week ago",
        campaigns,
        agent_ids=set(),
        # agent_created_at overrides start_time for cmp_old (10 days), cmp_new stays recent.
        agent_created_at={"cmp_old": _iso(10)},
    )
    ids = {c["id"] for c in selected}
    assert "cmp_old" in ids
    assert "cmp_new" not in ids  # 1 day old -> recent
    assert "cmp_no_ts" not in ids  # no timestamp -> conservatively excluded
    assert any("over a week" in label for label in labels)


def test_resolve_active_excluded_unless_named():
    campaigns = [
        {"id": "cmp_active", "name": "Big Active Promo", "effective_status": "ACTIVE"},
        {"id": "cmp_idle", "name": "Idle One", "effective_status": "PAUSED"},
    ]
    # Active dropped when not named.
    selected, _ = resolve_target_campaigns(
        "archive all campaigns",
        campaigns,
        agent_ids=set(),
        agent_created_at={},
    )
    assert {c["id"] for c in selected} == {"cmp_idle"}

    # Named active campaign IS included.
    selected_named, _ = resolve_target_campaigns(
        "archive Big Active Promo and the idle ones",
        campaigns,
        agent_ids=set(),
        agent_created_at={},
    )
    assert "cmp_active" in {c["id"] for c in selected_named}


def test_resolve_cap_to_50():
    campaigns = [
        {"id": f"cmp_{i}", "name": f"C{i}", "effective_status": "PAUSED"} for i in range(60)
    ]
    selected, labels = resolve_target_campaigns(
        "archive all your campaigns",
        campaigns,
        agent_ids={f"cmp_{i}" for i in range(60)},
        agent_created_at={},
    )
    assert len(selected) == 50
    assert any("capped" in label for label in labels)


def test_build_manage_approval_shape_and_none_on_empty():
    assert build_manage_approval("archive", [], account_id="act_1", filter_labels=[], reason="r") is None

    campaigns = [{"id": "cmp_a", "name": "A", "effective_status": "PAUSED"}]
    archive = build_manage_approval("archive", campaigns, account_id="act_1", filter_labels=["idle"], reason="bulk")
    assert archive["actionType"] == "manage_campaigns"
    assert archive["after"]["status"] == "ARCHIVED"
    assert archive["after"]["campaigns"][0]["id"] == "cmp_a"
    assert archive["target"]["level"] == "campaign_set"
    assert archive["target"]["name"] == "1 campaigns"
    assert archive["risk"] == "medium"
    assert archive["status"] == "needs_review"
    assert archive["filterLabels"] == ["idle"]

    pause = build_manage_approval("pause", campaigns, account_id="act_1", filter_labels=[], reason="bulk")
    assert pause["after"]["status"] == "PAUSED"
    assert pause["risk"] == "low"


def test_build_manage_approval_warns_on_active():
    campaigns = [{"id": "cmp_a", "name": "A", "effective_status": "ACTIVE"}]
    approval = build_manage_approval("pause", campaigns, account_id="act_1", filter_labels=[], reason="bulk")
    assert approval["guardrailResult"] == "warn"
    assert any(c["result"] == "warn" for c in approval["guardrailChecks"])


def test_format_manage_answer_contains_names_and_approve():
    approval = build_manage_approval(
        "archive",
        [
            {"id": "cmp_a", "name": "Income VSL", "effective_status": "PAUSED"},
            {"id": "cmp_b", "name": "Business VSL", "effective_status": "PAUSED"},
        ],
        account_id="act_1",
        filter_labels=["created by the agent"],
        reason="bulk",
    )
    text = format_manage_answer(approval)
    assert "Income VSL" in text
    assert "Business VSL" in text
    assert "approve" in text.lower()
    assert "Archive 2 campaigns" in text
    assert "created by the agent" in text
