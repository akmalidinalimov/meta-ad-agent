import threading

from backend import approval_store
from backend.storage_io import read_json, update_json, write_json_atomic


def test_write_json_atomic_roundtrip(tmp_path):
    path = tmp_path / "data.json"
    write_json_atomic(path, [{"id": "a"}])
    assert read_json(path, []) == [{"id": "a"}]
    # No leftover temp files in the directory.
    assert [p.name for p in tmp_path.iterdir()] == ["data.json"]


def test_read_json_returns_default_on_corruption(tmp_path):
    path = tmp_path / "corrupt.json"
    path.write_text("{not valid json", encoding="utf-8")
    assert read_json(path, []) == []


def test_concurrent_approval_updates_do_not_lose_writes(tmp_path):
    storage = tmp_path / "storage"
    # Seed 20 approval requests.
    for i in range(20):
        approval_store.create_approval_request({"id": f"a{i}", "status": "needs_review"}, storage_dir=storage)

    # Concurrently approve all of them from many threads (lock-guarded RMW must not
    # drop any update — the old unlocked read-modify-write would lose most of them).
    def approve(i: int) -> None:
        approval_store.approve_request(f"a{i}", approved_by="tester", storage_dir=storage)

    threads = [threading.Thread(target=approve, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    rows = approval_store.list_approval_requests(storage_dir=storage)
    assert len(rows) == 20
    assert all(row["status"] == "approved" for row in rows)


def test_update_json_locks_read_modify_write(tmp_path):
    path = tmp_path / "counter.json"
    write_json_atomic(path, {"n": 0})

    def increment() -> None:
        def mutate(data):
            data["n"] += 1
            return data["n"]
        update_json(path, mutate, default={"n": 0})

    threads = [threading.Thread(target=increment) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert read_json(path, {"n": 0})["n"] == 50
