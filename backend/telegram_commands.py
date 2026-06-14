from __future__ import annotations

from typing import Any


def normalize_telegram_command(payload: dict[str, Any]) -> dict[str, Any]:
    callback = payload.get("callback_query") or {}
    message = payload.get("message") or callback.get("message") or {}
    # On a callback_query, callback.from is the human who tapped the button, while
    # message.from is the BOT that authored the proposal message. The clicker must
    # win, or every inline button (Approve/Reject, drill-downs) is attributed to
    # the bot and the RBAC gate denies even the owner. callback.from therefore
    # precedes message.from; for a plain text message callback is empty and
    # message.from (the human) is used as before.
    sender = payload.get("from") or callback.get("from") or message.get("from") or {}
    chat = message.get("chat") or {}
    data = str(callback.get("data") or "").strip()
    text = str(message.get("text") or payload.get("text") or "").strip()

    return {
        "chatId": as_text(chat.get("id") or payload.get("chat_id")),
        "userId": as_text(sender.get("id") or payload.get("user_id")),
        "username": sender.get("username") or payload.get("username"),
        "text": text,
        "callbackData": data,
        "action": callback_action(data),
        "approvalId": callback_target(data),
    }


def callback_action(data: str) -> str | None:
    if not data or ":" not in data:
        return None
    return data.split(":", 1)[0].strip().lower()


def callback_target(data: str) -> str | None:
    if not data or ":" not in data:
        return None
    target = data.split(":", 1)[1].strip()
    return target or None


def as_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
