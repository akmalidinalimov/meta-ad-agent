from backend.approval_store import approve_request, create_approval_request, list_approval_requests
from backend.meta_execution import build_campaign_creation_approval
from backend.test_strategy_generator import sample_playbook


def test_create_and_list_approval_requests(tmp_path):
    storage_dir = tmp_path / "storage"
    request = build_campaign_creation_approval(sample_playbook(), account_id="act_123")

    saved = create_approval_request(request, storage_dir=storage_dir)
    rows = list_approval_requests(storage_dir=storage_dir)

    assert saved["id"].startswith("approval_")
    assert rows[0]["id"] == saved["id"]
    assert rows[0]["status"] == "needs_review"


def test_approve_request_records_user_and_timestamp(tmp_path):
    storage_dir = tmp_path / "storage"
    saved = create_approval_request(
        build_campaign_creation_approval(sample_playbook(), account_id="act_123"),
        storage_dir=storage_dir,
    )

    approved = approve_request(saved["id"], approved_by="akmal", storage_dir=storage_dir)

    assert approved["status"] == "approved"
    assert approved["approvedBy"] == "akmal"
    assert approved["approvedAt"]
