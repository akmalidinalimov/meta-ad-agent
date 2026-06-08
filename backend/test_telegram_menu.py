from fastapi.testclient import TestClient

import backend.routers.telegram as telegram_router
import backend.telegram_outbound as telegram_outbound
import backend.telegram_setup as telegram_setup
from backend.app import app
from backend.chat_service import to_telegram_html
from backend.telegram_menus import main_menu_keyboard, welcome_text


def test_main_menu_keyboard_has_core_buttons():
    kb = main_menu_keyboard()
    data = [b["callback_data"] for row in kb["inline_keyboard"] for b in row]
    assert "menu:kpis" in data
    assert "menu:suggestions" in data
    assert "menu:analytics" in data


def test_welcome_text_mentions_control_center():
    assert "control center" in welcome_text().lower()


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


def _open_bot(monkeypatch):
    for var in ("TELEGRAM_COMMAND_SECRET", "TELEGRAM_ALLOWED_CHAT_IDS", "TELEGRAM_ALLOWED_USER_IDS", "TELEGRAM_ADMIN_CHAT_ID"):
        monkeypatch.delenv(var, raising=False)
    sent = []
    monkeypatch.setattr(telegram_outbound, "send_telegram_message_sync", lambda text, **kwargs: sent.append((text, kwargs)) or {"ok": True})
    monkeypatch.setattr(telegram_outbound, "answer_callback_query", lambda *a, **k: {"ok": True})
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


def test_question_routes_to_conversational_chat(monkeypatch):
    sent = _open_bot(monkeypatch)
    monkeypatch.setattr(
        telegram_router,
        "answer_agent_question_sync",
        lambda message: {"answer": "Scale **Business education** next.", "sources": ["test"]},
    )
    client = TestClient(app)
    resp = client.post(
        "/api/telegram/command",
        json={"message": {"chat": {"id": 1001}, "from": {"username": "a"}, "text": "Which audience should I scale?"}},
    )
    assert resp.status_code == 200
    assert resp.json()["answer"].startswith("Scale")
    assert any("<b>Business education</b>" in text for text, _ in sent)
