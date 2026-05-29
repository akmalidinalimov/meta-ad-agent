import asyncio

from backend.meta_execution import execute_meta_action_approval


class FakeMetaWriter:
    def __init__(self):
        self.calls = []

    async def update_campaign(self, object_id, payload):
        self.calls.append(("campaign", object_id, payload))
        return {"success": True, "id": object_id, **payload}

    async def update_ad_set(self, object_id, payload):
        self.calls.append(("adset", object_id, payload))
        return {"success": True, "id": object_id, **payload}

    async def update_ad(self, object_id, payload):
        self.calls.append(("ad", object_id, payload))
        return {"success": True, "id": object_id, **payload}


def test_execute_approved_campaign_rename():
    writer = FakeMetaWriter()
    approval = {
        "id": "approval_rename",
        "status": "approved",
        "actionType": "rename_meta_object",
        "target": {"level": "campaign", "id": "120123"},
        "after": {"name": "Business Automation VSL - Tashkent"},
    }

    result = asyncio.run(execute_meta_action_approval(approval, writer=writer))

    assert result["ok"] is True
    assert writer.calls == [("campaign", "120123", {"name": "Business Automation VSL - Tashkent"})]


def test_execute_approved_adset_budget_change_converts_usd_to_meta_minor_units():
    writer = FakeMetaWriter()
    approval = {
        "id": "approval_budget",
        "status": "approved",
        "actionType": "change_meta_budget",
        "target": {"level": "adset", "id": "9988"},
        "after": {"daily_budget_usd": 120},
    }

    result = asyncio.run(execute_meta_action_approval(approval, writer=writer))

    assert result["ok"] is True
    assert writer.calls == [("adset", "9988", {"daily_budget": 12000})]


def test_execute_approved_ad_pause_and_enable():
    writer = FakeMetaWriter()
    pause = {
        "id": "approval_pause",
        "status": "approved",
        "actionType": "pause_meta_object",
        "target": {"level": "ad", "id": "7777"},
        "after": {"status": "PAUSED"},
    }
    enable = {
        "id": "approval_enable",
        "status": "approved",
        "actionType": "enable_meta_object",
        "target": {"level": "ad", "id": "7777"},
        "after": {"status": "ACTIVE"},
    }

    pause_result = asyncio.run(execute_meta_action_approval(pause, writer=writer))
    enable_result = asyncio.run(execute_meta_action_approval(enable, writer=writer))

    assert pause_result["ok"] is True
    assert enable_result["ok"] is True
    assert writer.calls == [
        ("ad", "7777", {"status": "PAUSED"}),
        ("ad", "7777", {"status": "ACTIVE"}),
    ]


def test_execute_rejects_unapproved_request():
    writer = FakeMetaWriter()
    approval = {
        "id": "approval_unapproved",
        "status": "needs_review",
        "actionType": "pause_meta_object",
        "target": {"level": "campaign", "id": "120123"},
        "after": {"status": "PAUSED"},
    }

    result = asyncio.run(execute_meta_action_approval(approval, writer=writer))

    assert result["ok"] is False
    assert result["blockedReason"] == "Approval must be approved before execution."
    assert writer.calls == []
