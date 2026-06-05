"""Tests for the proactive opportunity engine (WS-E).

Covers: packet generation contract (source/status/opportunity block), idempotent
same-day scheduling, new packet on a new day, send_alert spy, nothing executed,
and the force-generate endpoint surfacing the packet into GET /api/approvals.
"""

from __future__ import annotations

import asyncio
from datetime import date

from fastapi.testclient import TestClient

import backend.opportunity_finder as opportunity_finder
import backend.routers.opportunities as opportunities_module
from backend.app import app
from backend.opportunity_finder import (
    generate_opportunity_packets,
    list_opportunity_runs,
    run_scheduled_opportunities,
)
from backend.test_strategy_generator import sample_knowledge


def _knowledge() -> dict:
    # sample_knowledge carries ranked interests + regions/ageGender; add a winning
    # campaign config so the packet also mirrors a proven template.
    knowledge = sample_knowledge()
    knowledge["analysis"]["topCampaigns"] = [
        {
            "label": "Winning VSL",
            "keys": {"campaign_id": "cmp_win", "campaign_name": "Winning VSL"},
            "config": {
                "objective": "OUTCOME_SALES",
                "buyingType": "AUCTION",
                "specialAdCategories": [],
                "budgetMode": "CBO",
                "optimizationGoal": "OFFSITE_CONVERSIONS",
                "billingEvent": "IMPRESSIONS",
                "bidStrategy": "COST_CAP",
                "promotedObjectPixelId": "pixel_win",
            },
        }
    ]
    knowledge["analysis"]["topAds"] = [
        {
            "label": "Hero income proof",
            "keys": {"ad_id": "ad_1", "ad_name": "Hero income proof"},
            "creative": {"id": "creative_1", "name": "Hero income proof"},
            "qualityScore": 71,
            "hookRate": 28,
            "holdRate": 30,
            "purchases": 4,
        }
    ]
    return knowledge


# --- generate_opportunity_packets ------------------------------------------


def test_generate_opportunity_packets_emits_valid_proactive_approval():
    packets = generate_opportunity_packets(_knowledge(), [], today=date(2026, 6, 5))

    assert len(packets) == 1
    packet = packets[0]

    # Shared contract.
    assert packet["source"] == "proactive"
    assert packet["status"] == "needs_review"
    assert packet["id"] == "proactive_audience_test_20260605"
    assert packet["actionType"] == "create_paused_campaign_structure"

    opportunity = packet["opportunity"]
    assert isinstance(opportunity["rationale"], str) and opportunity["rationale"]
    assert opportunity["audiences"], "top-3 audiences attached"
    assert len(opportunity["audiences"]) <= 3
    assert opportunity["creatives"], "recommended creatives attached"
    assert all("newAngleBriefs" in block for block in opportunity["creatives"])
    assert opportunity["sourceTemplate"]["sourceCampaignId"] == "cmp_win"

    # Standard approval shape is preserved (campaign + paused ad sets, guardrails).
    assert packet["after"]["campaign"]["status"] == "PAUSED"
    assert packet["after"]["adsets"]
    assert all(adset["status"] == "PAUSED" for adset in packet["after"]["adsets"])
    assert "guardrailResult" in packet


def test_generate_opportunity_packets_excludes_recently_tested_audiences():
    recent_playbook = {
        "segments": [{"interests": ["Graphic design"]}],
    }
    packets = generate_opportunity_packets(_knowledge(), [recent_playbook], today=date(2026, 6, 5))

    suggested = {a["label"] for a in packets[0]["opportunity"]["audiences"]}
    assert "Graphic design" not in suggested
    assert "Graphic design" in packets[0]["opportunity"]["excludedRecentlyTested"]


def test_generate_opportunity_packets_returns_empty_without_knowledge():
    assert generate_opportunity_packets(None, []) == []
    assert generate_opportunity_packets({}, []) == []
    # Analysis present but no interests -> no audience to test -> empty.
    assert generate_opportunity_packets({"analysis": {"audience": {}}}, []) == []


# --- run_scheduled_opportunities -------------------------------------------


def test_scheduled_opportunities_is_idempotent_same_day(tmp_path):
    storage_dir = tmp_path / "storage"
    sent: list[dict] = []

    def send_alert(approval: dict) -> dict:
        sent.append(approval)
        return {"ok": True}

    first = asyncio.run(
        run_scheduled_opportunities(
            _knowledge,
            load_playbooks=lambda: [],
            storage_dir=storage_dir,
            send_alert=send_alert,
            enrich_creatives=False,
            today=date(2026, 6, 5),
        )
    )
    # Force the second same-day run (bypass the 24h debounce) to prove the
    # deterministic id REPLACES rather than duplicates.
    second = asyncio.run(
        run_scheduled_opportunities(
            _knowledge,
            load_playbooks=lambda: [],
            storage_dir=storage_dir,
            send_alert=send_alert,
            enrich_creatives=False,
            force=True,
            today=date(2026, 6, 5),
        )
    )

    assert first["ok"] is True and first["skipped"] is False
    assert second["ok"] is True and second["skipped"] is False

    # send_alert spy fired on each completed run.
    assert len(sent) == 2

    # Same deterministic id both days -> exactly one approval row in the store.
    from backend.approval_store import list_approval_requests

    approvals = list_approval_requests(storage_dir=storage_dir)
    proactive = [a for a in approvals if a.get("source") == "proactive"]
    assert len(proactive) == 1
    assert proactive[0]["id"] == "proactive_audience_test_20260605"

    # Nothing executed: status stays needs_review, no execution log.
    assert proactive[0]["status"] == "needs_review"
    assert "executionLog" not in proactive[0]
    assert proactive[0].get("lastExecutionResult") is None


def test_scheduled_opportunities_debounces_within_interval(tmp_path):
    storage_dir = tmp_path / "storage"

    first = asyncio.run(
        run_scheduled_opportunities(
            _knowledge,
            load_playbooks=lambda: [],
            storage_dir=storage_dir,
            enrich_creatives=False,
            today=date(2026, 6, 5),
        )
    )
    # No force, same interval -> skipped by the 24h debounce.
    second = asyncio.run(
        run_scheduled_opportunities(
            _knowledge,
            load_playbooks=lambda: [],
            storage_dir=storage_dir,
            enrich_creatives=False,
            today=date(2026, 6, 5),
        )
    )

    assert first["skipped"] is False
    assert second["skipped"] is True
    runs = list_opportunity_runs(storage_dir=storage_dir)
    assert runs[0]["status"] == "skipped"
    assert runs[1]["status"] == "completed"


def test_scheduled_opportunities_creates_new_packet_on_a_new_day(tmp_path):
    storage_dir = tmp_path / "storage"

    asyncio.run(
        run_scheduled_opportunities(
            _knowledge,
            load_playbooks=lambda: [],
            storage_dir=storage_dir,
            enrich_creatives=False,
            today=date(2026, 6, 5),
        )
    )
    # A different `today` makes a NEW suggestion (force bypasses the time debounce;
    # the id differs because it is date-derived).
    asyncio.run(
        run_scheduled_opportunities(
            _knowledge,
            load_playbooks=lambda: [],
            storage_dir=storage_dir,
            enrich_creatives=False,
            force=True,
            today=date(2026, 6, 6),
        )
    )

    from backend.approval_store import list_approval_requests

    proactive = [a for a in list_approval_requests(storage_dir=storage_dir) if a.get("source") == "proactive"]
    ids = {a["id"] for a in proactive}
    assert ids == {"proactive_audience_test_20260605", "proactive_audience_test_20260606"}


def test_scheduled_opportunities_defensive_when_no_knowledge(tmp_path):
    storage_dir = tmp_path / "storage"
    sent: list[dict] = []

    result = asyncio.run(
        run_scheduled_opportunities(
            lambda: None,
            load_playbooks=lambda: [],
            storage_dir=storage_dir,
            send_alert=lambda approval: sent.append(approval) or {"ok": True},
            enrich_creatives=False,
            today=date(2026, 6, 5),
        )
    )

    assert result["ok"] is True
    assert result["run"]["status"] == "completed"
    assert result["run"]["approvalsCreated"] == 0
    assert sent == []


# --- endpoints --------------------------------------------------------------


def test_generate_endpoint_returns_packet_and_appears_in_approvals(monkeypatch, tmp_path):
    storage_dir = tmp_path / "storage"

    # Bind the engine to a temp store + synthetic knowledge so the test never
    # touches real on-disk data and is deterministic with no LLM key.
    monkeypatch.setattr(opportunities_module, "load_knowledge_base", _knowledge)
    monkeypatch.setattr(opportunities_module, "load_playbooks", lambda: [])
    sent: list[dict] = []
    monkeypatch.setattr(
        opportunities_module,
        "send_approval_notification",
        lambda approval: sent.append(approval) or {"ok": True},
    )

    async def _run(load_knowledge, **kwargs):
        kwargs["storage_dir"] = storage_dir
        kwargs["enrich_creatives"] = False
        return await opportunity_finder.run_scheduled_opportunities(load_knowledge, **kwargs)

    monkeypatch.setattr(opportunities_module, "run_scheduled_opportunities", _run)

    # Point the /api/approvals reader at the same temp store the engine wrote to.
    import backend.routers.approvals as approvals_router_mod
    from backend.approval_store import list_approval_requests

    monkeypatch.setattr(
        approvals_router_mod,
        "list_approval_requests",
        lambda: list_approval_requests(storage_dir=storage_dir),
    )

    client = TestClient(app)
    response = client.post("/api/opportunities/generate", json={})

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert len(payload["approvals"]) == 1
    approval = payload["approvals"][0]
    assert approval["source"] == "proactive"
    assert approval["status"] == "needs_review"
    assert approval["opportunity"]["audiences"]
    assert sent, "Telegram/web-queue notification fired"

    # It appears in the operator's approval queue.
    listed = client.get("/api/approvals").json()["approvals"]
    assert any(item["id"] == approval["id"] and item["source"] == "proactive" for item in listed)
    # Still suggest-only: nothing executed.
    assert all(item.get("status") != "executed" for item in listed)
