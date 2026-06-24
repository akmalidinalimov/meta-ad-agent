import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from fastapi.testclient import TestClient

from backend.app import app
from backend.webapp_auth import make_session, user_allowed, valid_session, validate_init_data

TOKEN = "123456:TEST-bot-token"


def _make_init_data(
    token: str, user: dict, *, auth_date: int | None = None, signature: str | None = None
) -> str:
    pairs = {
        "auth_date": str(auth_date or int(time.time())),
        "query_id": "AAA",
        "user": json.dumps(user, separators=(",", ":")),
    }
    if signature is not None:
        # Real Telegram clients include `signature` in the HMAC data-check-string.
        pairs["signature"] = signature
    data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    pairs["hash"] = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(pairs)


def test_validate_init_data_accepts_valid_and_rejects_tampered(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    init = _make_init_data(TOKEN, {"id": 42, "username": "op"})
    user = validate_init_data(init)
    assert user and user["id"] == 42
    assert validate_init_data(init + "x") is None  # tampered hash
    assert validate_init_data(_make_init_data("999:other", {"id": 42})) is None  # wrong token


def test_validate_init_data_includes_signature_field(monkeypatch):
    # Newer clients add an Ed25519 `signature` field. Verified live that Telegram
    # INCLUDES it in the HMAC data-check-string (only `hash` is excluded), so a real
    # initData carrying `signature` must validate.
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    init = _make_init_data(TOKEN, {"id": 5, "username": "op"}, signature="Zm9vYmFyYmF6")
    user = validate_init_data(init)
    assert user and user["id"] == 5


def test_validate_init_data_rejects_stale(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    old = _make_init_data(TOKEN, {"id": 1}, auth_date=int(time.time()) - 90000)
    assert validate_init_data(old, max_age_seconds=86400) is None


def test_session_roundtrip_and_forgery(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", "unit-secret")
    token = make_session("admin")
    assert valid_session(token) is True
    assert valid_session(token + "x") is False
    assert valid_session("admin.9999999999.deadbeef") is False


def test_login_sets_session_cookie(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", "letmein")
    monkeypatch.setenv("SESSION_SECRET", "unit-secret")
    client = TestClient(app)
    assert client.post("/api/auth/login", json={"password": "nope"}).status_code == 401
    ok = client.post("/api/auth/login", json={"password": "letmein"})
    assert ok.status_code == 200
    assert "session" in ok.cookies


def test_webapp_auth_with_valid_init_data(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("SESSION_SECRET", "unit-secret")
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)
    monkeypatch.delenv("TELEGRAM_ADMIN_CHAT_ID", raising=False)
    client = TestClient(app)
    init = _make_init_data(TOKEN, {"id": 7, "username": "op"})
    resp = client.post("/api/telegram/webapp-auth", json={"initData": init})
    assert resp.status_code == 200
    assert resp.json()["user"]["id"] == 7
    assert "session" in resp.cookies


def test_admin_chat_id_always_allowed_even_when_allowlist_excludes_it(monkeypatch):
    # The configured admin must never be locked out, even if TELEGRAM_ALLOWED_USER_IDS
    # is set to a different id.
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "999")
    monkeypatch.setenv("TELEGRAM_ADMIN_CHAT_ID", "42")
    assert user_allowed({"id": 42}) is True
    assert user_allowed({"id": 999}) is True
    assert user_allowed({"id": 5}) is False


def test_webapp_auth_rejection_logs_cause(monkeypatch, caplog):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("SESSION_SECRET", "unit-secret")
    monkeypatch.delenv("TELEGRAM_ALLOWED_USER_IDS", raising=False)
    monkeypatch.delenv("TELEGRAM_ADMIN_CHAT_ID", raising=False)
    client = TestClient(app)
    init = _make_init_data(TOKEN, {"id": 7, "username": "op"})
    with caplog.at_level("WARNING"):
        resp = client.post("/api/telegram/webapp-auth", json={"initData": init + "x"})
    assert resp.status_code == 401
    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "bad hash" in messages  # cause from validate_init_data
    assert "webapp-auth rejected" in messages  # cause from the router


def test_session_guard_blocks_without_cookie_when_enabled(monkeypatch):
    monkeypatch.setenv("DASHBOARD_SESSION_AUTH", "true")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "letmein")
    monkeypatch.setenv("SESSION_SECRET", "unit-secret")

    blocked = TestClient(app)
    # No session -> a data endpoint is gated, health + auth stay public.
    assert blocked.get("/api/targets").status_code == 401
    assert blocked.get("/api/health").status_code == 200

    # A valid session cookie passes the guard (passed explicitly because the Secure
    # cookie is not auto-sent over the test client's http scheme).
    authed = TestClient(app)
    assert authed.get("/api/targets", cookies={"session": make_session("admin")}).status_code == 200
