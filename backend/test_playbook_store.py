from backend.playbook_store import default_playbook, load_playbooks, save_playbook


def test_default_playbook_is_configurable_not_hardcoded_to_three_segments():
    playbook = default_playbook()

    assert playbook["name"] == "Configurable AI course launch"
    assert playbook["primarySuccessMetric"] == "telegram_start"
    assert playbook["segments"] == []
    assert playbook["rules"]["scalingStepPercent"] == 20


def test_save_playbook_persists_arbitrary_segment_count(tmp_path):
    storage_dir = tmp_path / "storage"
    playbook = default_playbook()
    playbook["id"] = "pb_test"
    playbook["segments"] = [
        {"id": "income", "name": "Income", "vslId": "vsl_1", "startingBudgetUsd": 100},
        {"id": "business", "name": "Business", "vslId": "vsl_2", "startingBudgetUsd": 150},
        {"id": "creator", "name": "Creator", "vslId": "vsl_3", "startingBudgetUsd": 80},
        {"id": "employee", "name": "Employee", "vslId": "vsl_4", "startingBudgetUsd": 120},
    ]

    saved = save_playbook(playbook, storage_dir=storage_dir)
    playbooks = load_playbooks(storage_dir=storage_dir)

    assert saved["id"] == "pb_test"
    assert len(playbooks[0]["segments"]) == 4
