from backend.targets_store import default_targets, has_any_target, load_targets, save_targets


def test_default_targets_all_none():
    assert load_targets(storage_dir=_empty_dir()) == default_targets()


def test_save_and_load_roundtrip(tmp_path):
    save_targets({"maxCpl": 0.1, "minLeadRate": 40}, storage_dir=tmp_path)
    loaded = load_targets(storage_dir=tmp_path)
    assert loaded["maxCpl"] == 0.1
    assert loaded["minLeadRate"] == 40.0
    assert loaded["maxCostPerStart"] is None


def test_partial_update_keeps_existing(tmp_path):
    save_targets({"maxCpl": 0.1}, storage_dir=tmp_path)
    save_targets({"minStartRate": 5}, storage_dir=tmp_path)
    loaded = load_targets(storage_dir=tmp_path)
    assert loaded["maxCpl"] == 0.1
    assert loaded["minStartRate"] == 5.0


def test_zero_or_blank_coerces_to_none(tmp_path):
    save_targets({"maxCpl": 0, "minLeadRate": ""}, storage_dir=tmp_path)
    loaded = load_targets(storage_dir=tmp_path)
    assert loaded["maxCpl"] is None
    assert loaded["minLeadRate"] is None
    assert not has_any_target(loaded)


def test_weekly_budget_target_round_trips(tmp_path):
    saved = save_targets({"weeklyBudgetTargetUsd": 500}, storage_dir=tmp_path)
    assert saved["weeklyBudgetTargetUsd"] == 500.0
    assert load_targets(storage_dir=tmp_path)["weeklyBudgetTargetUsd"] == 500.0


def test_weekly_budget_target_defaults_to_none(tmp_path):
    assert load_targets(storage_dir=tmp_path)["weeklyBudgetTargetUsd"] is None


def _empty_dir():
    import tempfile
    from pathlib import Path

    return Path(tempfile.mkdtemp())
