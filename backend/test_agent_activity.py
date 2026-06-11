"""Agent activity registry — live working state + persisted event feed."""

from backend import agent_activity


def setup_function():
    agent_activity.reset_live_for_tests()


def test_begin_marks_agent_working():
    agent_activity.begin("monitor", "scanning ad sets")
    live = agent_activity.live_state()
    assert live["monitor"]["activity"] == "scanning ad sets"
    assert live["monitor"]["startedAt"]


def test_unknown_agent_id_is_ignored():
    agent_activity.begin("ghost", "haunting")
    assert agent_activity.live_state() == {}


def test_end_without_summary_clears_live_and_persists_nothing(tmp_path):
    agent_activity.begin("monitor", "scanning ad sets")
    agent_activity.end("monitor", None, storage_dir=tmp_path)
    assert agent_activity.live_state() == {}
    assert agent_activity.stored(storage_dir=tmp_path)["events"] == []


def test_end_with_summary_persists_event_and_last_active(tmp_path):
    agent_activity.begin("planner", "daily opportunity review")
    agent_activity.end("planner", "opportunity review completed", storage_dir=tmp_path)

    assert agent_activity.live_state() == {}
    data = agent_activity.stored(storage_dir=tmp_path)
    assert data["events"][0]["agentId"] == "planner"
    assert data["events"][0]["summary"] == "opportunity review completed"
    assert data["events"][0]["at"]
    assert data["lastActive"]["planner"]["summary"] == "opportunity review completed"


def test_end_without_begin_still_records_event(tmp_path):
    # e.g. a job that only reports completion
    agent_activity.end("analyst", "KPI digest sent to Telegram", storage_dir=tmp_path)
    data = agent_activity.stored(storage_dir=tmp_path)
    assert data["events"][0]["agentId"] == "analyst"


def test_events_are_capped(tmp_path):
    for i in range(60):
        agent_activity.end("analyst", f"run {i}", storage_dir=tmp_path)
    data = agent_activity.stored(storage_dir=tmp_path)
    assert len(data["events"]) == agent_activity.MAX_EVENTS
    assert data["events"][0]["summary"] == "run 59"  # newest first


def test_stored_handles_missing_file(tmp_path):
    assert agent_activity.stored(storage_dir=tmp_path) == {"events": [], "lastActive": {}}
