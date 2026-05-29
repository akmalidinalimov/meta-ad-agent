from backend.agent_task_store import (
    create_agent_task,
    list_agent_tasks,
    update_agent_task,
)


def test_create_and_list_agent_tasks(tmp_path):
    task = create_agent_task(
        {
            "source": "dashboard",
            "command": "Create a paused campaign for three VSLs",
            "campaignGroupId": "launch_2026_06",
            "segmentIds": ["income", "business"],
        },
        storage_dir=tmp_path,
    )

    rows = list_agent_tasks(storage_dir=tmp_path)

    assert task["id"].startswith("task_")
    assert task["status"] == "draft"
    assert task["source"] == "dashboard"
    assert task["requestedAction"] == "Create a paused campaign for three VSLs"
    assert task["campaignGroupId"] == "launch_2026_06"
    assert task["segmentIds"] == ["income", "business"]
    assert task["createdAt"]
    assert rows == [task]


def test_update_agent_task_preserves_history_and_status(tmp_path):
    task = create_agent_task(
        {"source": "telegram", "command": "Prepare budget test"},
        storage_dir=tmp_path,
    )

    updated = update_agent_task(
        task["id"],
        {
            "status": "needs_approval",
            "activeAgent": "orchestrator",
            "plan": {"summary": "Prepare approval-safe budget test."},
            "approvalId": "approval_123",
        },
        storage_dir=tmp_path,
    )

    rows = list_agent_tasks(storage_dir=tmp_path)

    assert updated["status"] == "needs_approval"
    assert updated["activeAgent"] == "orchestrator"
    assert updated["plan"]["summary"] == "Prepare approval-safe budget test."
    assert updated["approvalId"] == "approval_123"
    assert updated["updatedAt"] != task["updatedAt"]
    assert rows[0]["history"][-1]["status"] == "needs_approval"
