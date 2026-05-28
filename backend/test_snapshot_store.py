from datetime import datetime, timezone

from backend.snapshot_store import (
    build_snapshot_payload,
    latest_snapshot,
    list_snapshots,
    save_snapshot,
)


def test_save_snapshot_persists_versioned_metadata(tmp_path):
    storage_dir = tmp_path / "storage"
    now = datetime(2026, 5, 28, 10, 30, tzinfo=timezone.utc)
    payload = build_snapshot_payload(
        raw={"campaigns": [{"id": "campaign_1"}], "insights": {"base": [{"id": "row_1"}]}},
        analysis={"summary": {"spend": 123}, "rawCounts": {"campaigns": 1}},
        account_id="act_123",
        days=90,
        generated_at=now,
    )

    snapshot = save_snapshot(payload, storage_dir=storage_dir)

    assert snapshot["id"] == "meta-act_123-20260528T103000Z-90d"
    assert snapshot["kind"] == "meta"
    assert snapshot["accountId"] == "act_123"
    assert snapshot["days"] == 90
    assert snapshot["rawCounts"] == {"campaigns": 1}
    assert (storage_dir / "snapshots" / "meta-act_123-20260528T103000Z-90d.json").exists()


def test_latest_snapshot_prefers_newest_generated_at(tmp_path):
    storage_dir = tmp_path / "storage"
    older = build_snapshot_payload(
        raw={"campaigns": []},
        analysis={"rawCounts": {"campaigns": 0}},
        account_id="act_123",
        days=90,
        generated_at=datetime(2026, 5, 27, 10, tzinfo=timezone.utc),
    )
    newer = build_snapshot_payload(
        raw={"campaigns": [{"id": "campaign_2"}]},
        analysis={"rawCounts": {"campaigns": 1}},
        account_id="act_123",
        days=180,
        generated_at=datetime(2026, 5, 28, 10, tzinfo=timezone.utc),
    )

    save_snapshot(older, storage_dir=storage_dir)
    save_snapshot(newer, storage_dir=storage_dir)

    snapshots = list_snapshots(storage_dir=storage_dir)
    assert [item["days"] for item in snapshots] == [180, 90]
    assert latest_snapshot(storage_dir=storage_dir)["days"] == 180
