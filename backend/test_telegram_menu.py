import os

from fastapi.testclient import TestClient

import backend.routers.telegram as telegram_router
import backend.telegram_outbound as telegram_outbound
import backend.telegram_setup as telegram_setup
from backend.app import app
from backend.chat_service import to_telegram_html
from backend.telegram_menus import (
    adset_ads_keyboard,
    alerts_campaign_keyboard,
    approval_adset_detail_keyboard,
    approval_adsets_keyboard,
    campaign_adsets_keyboard,
    campaigns_list_keyboard,
    main_menu_keyboard,
    main_reply_keyboard,
    pending_approvals_keyboard,
    pending_campaign_keyboard,
    suggestions_campaign_keyboard,
    welcome_text,
)


def test_main_menu_keyboard_has_core_buttons():
    kb = main_menu_keyboard()
    data = [b["callback_data"] for row in kb["inline_keyboard"] for b in row]
    assert "menu:kpis" in data
    assert "menu:suggestions" in data
    assert "menu:analytics" in data


def test_welcome_text_mentions_control_center():
    assert "control center" in welcome_text().lower()


def test_main_reply_keyboard_is_persistent_with_core_buttons():
    kb = main_reply_keyboard()
    assert kb["is_persistent"] is True
    assert kb["resize_keyboard"] is True
    labels = [b["text"] for row in kb["keyboard"] for b in row]
    assert "📊 KPIs" in labels
    assert "🤖 Suggestions" in labels
    # Task 6: the redundant Analytics reply button is gone (Dashboard menu button stays).
    assert "📊 Analytics" not in labels
    # Tasks 3 + 4: the new drill-down entry points are present.
    assert "📁 Campaigns" in labels
    assert "📝 Pending Approvals" in labels


def _all_callback_data(kb):
    return [b["callback_data"] for row in kb["inline_keyboard"] for b in row if "callback_data" in b]


def _all_labels(kb):
    return [b["text"] for row in kb["inline_keyboard"] for b in row]


def test_drilldown_keyboards_respect_callback_data_limit():
    long_id = "9" * 17  # Meta IDs are ~17 digits
    campaigns = [{"id": long_id, "name": "X" * 80, "status": "ACTIVE"}]
    adsets = [{"id": long_id, "name": "Y" * 80, "campaign_id": long_id, "status": "PAUSED"}]
    approval_id = "approval_20260101T000000Z"
    approvals = [{"id": approval_id, "after": {"campaign": {"name": "Z" * 80}}}]
    approval_adsets = [{"name": "S" * 80}]

    keyboards = [
        campaigns_list_keyboard(campaigns),
        campaign_adsets_keyboard(long_id, adsets),
        adset_ads_keyboard(long_id, long_id),
        pending_approvals_keyboard(approvals),
        approval_adsets_keyboard(approval_id, approval_adsets),
        approval_adset_detail_keyboard(approval_id),
    ]
    for kb in keyboards:
        for cd in _all_callback_data(kb):
            assert len(cd.encode("utf-8")) <= 64, cd


def test_drilldown_keyboards_have_back_buttons():
    long_id = "9" * 17
    adsets = [{"id": long_id, "name": "Ad set", "campaign_id": long_id}]
    assert "⬅️ Back" in _all_labels(campaign_adsets_keyboard(long_id, adsets))
    assert "⬅️ Back" in _all_labels(adset_ads_keyboard(long_id, long_id))
    assert "⬅️ Back" in _all_labels(approval_adsets_keyboard("a1", [{"name": "S"}]))
    assert "⬅️ Back" in _all_labels(approval_adset_detail_keyboard("a1"))


def test_campaigns_list_caps_at_twenty():
    campaigns = [{"id": str(i), "name": f"C{i}", "status": "ACTIVE"} for i in range(50)]
    kb = campaigns_list_keyboard(campaigns)
    assert len(kb["inline_keyboard"]) == 20


def test_to_telegram_html_converts_bold_and_escapes():
    out = to_telegram_html("CPL is **0.06** and 1 < 2")
    assert "<b>0.06</b>" in out
    assert "&lt; 2" in out  # '<' is HTML-escaped, not left raw


def test_register_bot_ui_registers_commands_and_menu_button(monkeypatch):
    calls = []
    monkeypatch.setattr(telegram_setup, "telegram_api", lambda method, payload: calls.append((method, payload)) or {"ok": True})
    telegram_setup.register_bot_ui()
    methods = [m for m, _ in calls]
    assert "setMyCommands" in methods
    assert "setChatMenuButton" in methods


def _seed_owner(monkeypatch, username="a"):
    """RBAC gate: isolate the members store to a tmp file and seed the test caller
    (@a) as the owner so the existing button/callback flows stay authorized."""
    import json
    import tempfile

    fd, path = tempfile.mkstemp(suffix="_members.json")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(
            [{"userId": None, "username": username, "role": "owner",
              "addedBy": "system", "addedAt": "2026-01-01T00:00:00+00:00"}],
            fh,
        )
    monkeypatch.setenv("MEMBERS_STORE_PATH", path)


def _open_bot(monkeypatch):
    for var in ("TELEGRAM_COMMAND_SECRET", "TELEGRAM_ALLOWED_CHAT_IDS", "TELEGRAM_ALLOWED_USER_IDS", "TELEGRAM_ADMIN_CHAT_ID"):
        monkeypatch.delenv(var, raising=False)
    _seed_owner(monkeypatch)
    sent = []
    monkeypatch.setattr(telegram_outbound, "send_telegram_message_sync", lambda text, **kwargs: sent.append((text, kwargs)) or {"ok": True})
    monkeypatch.setattr(telegram_outbound, "answer_callback_query", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(telegram_outbound, "edit_message_reply_markup", lambda *a, **k: {"ok": True})
    return sent


def test_menu_status_callback_replies_with_status(monkeypatch):
    sent = _open_bot(monkeypatch)
    client = TestClient(app)
    resp = client.post(
        "/api/telegram/command",
        json={"callback_query": {"from": {"id": 1, "username": "a"}, "message": {"chat": {"id": 1001}}, "data": "menu:status"}},
    )
    assert resp.status_code == 200
    assert resp.json()["menu"] == "status"
    assert any("Agent status" in text for text, _ in sent)


def test_start_text_sends_main_menu(monkeypatch):
    sent = _open_bot(monkeypatch)
    client = TestClient(app)
    resp = client.post("/api/telegram/command", json={"message": {"chat": {"id": 1001}, "from": {"username": "a"}, "text": "/start"}})
    assert resp.status_code == 200
    assert resp.json()["menu"] == "main"
    assert any("reply_markup" in kwargs for _, kwargs in sent)


def test_reply_button_label_routes_to_action(monkeypatch):
    sent = _open_bot(monkeypatch)
    client = TestClient(app)
    resp = client.post(
        "/api/telegram/command",
        json={"message": {"chat": {"id": 1001}, "from": {"username": "a"}, "text": "📈 Status"}},
    )
    assert resp.status_code == 200
    assert resp.json()["menu"] == "status"
    assert any("Agent status" in text for text, _ in sent)


def test_apply_flow_dryrun_then_applylive(monkeypatch):
    sent = _open_bot(monkeypatch)
    monkeypatch.setattr(
        telegram_router,
        "dry_run_sync",
        lambda aid: {"ok": True, "result": {"wouldCreate": {"campaign": {"name": "Test - DRAFT"}, "adsets": [1, 2, 3]}}},
    )
    monkeypatch.setattr(
        telegram_router,
        "apply_live_sync",
        lambda aid: {"ok": True, "result": {"created": [{"level": "campaign", "id": "123", "name": "Test - DRAFT"}]}},
    )
    client = TestClient(app)

    r1 = client.post(
        "/api/telegram/command",
        json={"callback_query": {"message": {"chat": {"id": 1001}, "message_id": 5}, "from": {"username": "a"}, "data": "dryrun:appA"}},
    )
    assert r1.status_code == 200 and r1.json()["dryRun"] is True
    assert any("Dry run" in text for text, _ in sent)

    r2 = client.post(
        "/api/telegram/command",
        json={"callback_query": {"message": {"chat": {"id": 1001}, "message_id": 5}, "from": {"username": "a"}, "data": "applylive:appA"}},
    )
    assert r2.status_code == 200 and r2.json()["applied"] is True
    assert any("Created in Meta" in text for text, _ in sent)


def test_apply_live_reports_meta_error(monkeypatch):
    sent = _open_bot(monkeypatch)
    monkeypatch.setattr(telegram_router, "apply_live_sync", lambda aid: {"ok": False, "error": "Meta API rejected the write: bad bid"})
    client = TestClient(app)
    resp = client.post(
        "/api/telegram/command",
        json={"callback_query": {"message": {"chat": {"id": 1001}, "message_id": 5}, "from": {"username": "a"}, "data": "applylive:appA"}},
    )
    assert resp.status_code == 200 and resp.json()["ok"] is False
    assert any("Meta rejected" in text for text, _ in sent)


# --- Task 16: Suggestions / Alerts / Pending grouped by campaign ------------------


def test_campaign_picker_keyboards_callbacks_and_limit():
    long_id = "9" * 17  # Meta IDs are ~17 digits
    groups = [{"id": long_id, "name": "X" * 80, "count": 3}]
    for kb, prefix in [
        (suggestions_campaign_keyboard(groups), "sug:c:"),
        (alerts_campaign_keyboard(groups), "alr:c:"),
        (pending_campaign_keyboard(groups), "apv:gc:"),
    ]:
        cds = _all_callback_data(kb)
        assert cds == [f"{prefix}{long_id}"]
        for cd in cds:
            assert len(cd.encode("utf-8")) <= 64, cd
        assert any("· 3" in b["text"] for row in kb["inline_keyboard"] for b in row)


def test_campaign_picker_uses_none_sentinel_for_missing_campaign():
    groups = [{"id": "", "name": "Other", "count": 1}]
    assert _all_callback_data(suggestions_campaign_keyboard(groups)) == ["sug:c:none"]


def test_campaign_picker_caps_at_twenty():
    groups = [{"id": str(i), "name": f"C{i}", "count": 1} for i in range(50)]
    assert len(suggestions_campaign_keyboard(groups)["inline_keyboard"]) == 20


def test_group_by_campaign_orders_by_count_then_name():
    items = [
        {"after": {"campaign": {"id": "1", "name": "Alpha"}}},
        {"after": {"campaign": {"id": "2", "name": "Beta"}}},
        {"after": {"campaign": {"id": "2", "name": "Beta"}}},
        {"actionType": "manage_campaigns"},  # no campaign -> Other bucket
    ]
    groups = telegram_router._group_by_campaign(items, telegram_router._approval_campaign)
    assert [(g["id"], g["count"]) for g in groups] == [("2", 2), ("1", 1), ("", 1)]
    assert telegram_router._find_group(groups, "none")["name"] == "manage_campaigns"
    assert telegram_router._find_group(groups, "2")["count"] == 2


def test_menu_suggestions_shows_campaign_picker(monkeypatch):
    sent = _open_bot(monkeypatch)
    monkeypatch.setattr(
        telegram_router,
        "list_approval_requests",
        lambda: [
            {"id": "a1", "status": "needs_review", "after": {"campaign": {"id": "11", "name": "VSL Test"}}},
            {"id": "a2", "status": "needs_review", "after": {"campaign": {"id": "11", "name": "VSL Test"}}},
            {"id": "a3", "status": "approved", "after": {"campaign": {"id": "22", "name": "Other"}}},
        ],
    )
    client = TestClient(app)
    resp = client.post(
        "/api/telegram/command",
        json={"callback_query": {"from": {"id": 1, "username": "a"}, "message": {"chat": {"id": 1001}}, "data": "menu:suggestions"}},
    )
    assert resp.status_code == 200 and resp.json()["menu"] == "suggestions"
    # Only the 2 needs_review items count; the picker offers campaign 11.
    assert any("Suggestions</b> (2)" in text for text, _ in sent)
    assert any(
        any(b.get("callback_data") == "sug:c:11" for row in (kwargs.get("reply_markup") or {}).get("inline_keyboard", []) for b in row)
        for _, kwargs in sent
    )


def test_suggestions_drill_sends_only_that_campaigns_cards(monkeypatch):
    _open_bot(monkeypatch)
    monkeypatch.setattr(telegram_outbound, "edit_message_text", lambda *a, **k: {"ok": True})
    notified: list[str] = []
    monkeypatch.setattr(telegram_outbound, "send_approval_notification", lambda approval: notified.append(approval.get("id")))
    monkeypatch.setattr(
        telegram_router,
        "list_approval_requests",
        lambda: [
            {"id": "a1", "status": "needs_review", "after": {"campaign": {"id": "11", "name": "VSL Test"}}},
            {"id": "a2", "status": "needs_review", "after": {"campaign": {"id": "11", "name": "VSL Test"}}},
            {"id": "a3", "status": "needs_review", "after": {"campaign": {"id": "22", "name": "Other"}}},
        ],
    )
    client = TestClient(app)
    resp = client.post(
        "/api/telegram/command",
        json={"callback_query": {"from": {"id": 1, "username": "a"}, "message": {"chat": {"id": 1001}, "message_id": 7}, "data": "sug:c:11"}},
    )
    assert resp.status_code == 200
    assert notified == ["a1", "a2"]  # campaign 22's suggestion is NOT sent


def test_menu_alerts_picker_then_campaign_drill(monkeypatch):
    import backend.monitoring_runner as monitoring_runner

    sent = _open_bot(monkeypatch)
    monkeypatch.setattr(telegram_outbound, "edit_message_text", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(
        monitoring_runner,
        "list_monitoring_alerts",
        lambda **kw: [
            {"id": "al1", "severity": "high", "title": "CPL spike", "campaignId": "11", "campaignName": "VSL Test", "recommendedActions": ["Lower bid"]},
            {"id": "al2", "severity": "medium", "title": "CTR drop", "campaignId": "11", "campaignName": "VSL Test"},
        ],
    )
    client = TestClient(app)
    r1 = client.post(
        "/api/telegram/command",
        json={"callback_query": {"from": {"id": 1, "username": "a"}, "message": {"chat": {"id": 1001}}, "data": "menu:alerts"}},
    )
    assert r1.json()["menu"] == "alerts"
    assert any("Alerts</b> (2)" in text for text, _ in sent)
    r2 = client.post(
        "/api/telegram/command",
        json={"callback_query": {"from": {"id": 1, "username": "a"}, "message": {"chat": {"id": 1001}, "message_id": 8}, "data": "alr:c:11"}},
    )
    assert r2.json()["alerts"] == "11"


def test_menu_pending_picker_then_campaign_drill(monkeypatch):
    sent = _open_bot(monkeypatch)
    monkeypatch.setattr(telegram_outbound, "edit_message_text", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(
        telegram_router,
        "list_approval_requests",
        lambda: [
            {"id": "a1", "status": "needs_review", "after": {"campaign": {"id": "11", "name": "VSL Test"}, "adsets": [{"name": "AS1"}]}},
        ],
    )
    client = TestClient(app)
    r1 = client.post(
        "/api/telegram/command",
        json={"callback_query": {"from": {"id": 1, "username": "a"}, "message": {"chat": {"id": 1001}}, "data": "menu:pending"}},
    )
    assert r1.json()["menu"] == "pending"
    assert any("Pending Approvals</b> (1)" in text for text, _ in sent)
    r2 = client.post(
        "/api/telegram/command",
        json={"callback_query": {"from": {"id": 1, "username": "a"}, "message": {"chat": {"id": 1001}, "message_id": 9}, "data": "apv:gc:11"}},
    )
    assert r2.json()["pending"] == "campaign" and r2.json()["campaign"] == "11"


def test_question_routes_to_agentic_brain(monkeypatch):
    import backend.agentic_chat as agentic_chat
    import backend.pending_context_store as pending_store

    sent = _open_bot(monkeypatch)
    monkeypatch.setattr(pending_store, "get_pending", lambda op_key, **kw: None)

    async def fake_reply(message, *, operator_key):
        return "Scale <b>Business education</b> next."

    monkeypatch.setattr(agentic_chat, "agentic_reply", fake_reply)
    client = TestClient(app)
    resp = client.post(
        "/api/telegram/command",
        json={"message": {"chat": {"id": 1001}, "from": {"username": "a"}, "text": "Which audience should I scale?"}},
    )
    assert resp.status_code == 200
    assert resp.json()["agentic"] is True
    assert any("<b>Business education</b>" in text for text, _ in sent)
