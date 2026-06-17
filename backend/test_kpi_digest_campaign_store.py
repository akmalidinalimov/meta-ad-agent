from backend.kpi_digest_campaign_store import (
    clear_kpi_digest_campaign,
    load_kpi_digest_campaign,
    set_kpi_digest_campaign,
)


def test_load_returns_none_when_unset(tmp_path):
    assert load_kpi_digest_campaign(storage_dir=tmp_path) is None


def test_set_then_load_roundtrips(tmp_path):
    set_kpi_digest_campaign(
        "120246221262310733",
        "DA - SHAHLOAI - VSL - 16.06.2026",
        selected_by="telegram:akmal",
        storage_dir=tmp_path,
    )
    loaded = load_kpi_digest_campaign(storage_dir=tmp_path)
    assert loaded is not None
    assert loaded["campaignId"] == "120246221262310733"
    assert loaded["campaignName"] == "DA - SHAHLOAI - VSL - 16.06.2026"
    assert loaded["selectedBy"] == "telegram:akmal"
    assert loaded["selectedAt"]


def test_clear_resets_to_account_wide(tmp_path):
    set_kpi_digest_campaign("c1", "Camp", storage_dir=tmp_path)
    clear_kpi_digest_campaign(storage_dir=tmp_path)
    assert load_kpi_digest_campaign(storage_dir=tmp_path) is None
    # Reset keeps the file (empty object), it is not deleted.
    assert (tmp_path / "kpi_digest_campaign.json").exists()


def test_set_coerces_ids_to_strings(tmp_path):
    set_kpi_digest_campaign(120246221262310733, storage_dir=tmp_path)
    loaded = load_kpi_digest_campaign(storage_dir=tmp_path)
    assert loaded["campaignId"] == "120246221262310733"
