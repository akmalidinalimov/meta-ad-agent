from __future__ import annotations

from typing import Any


def normalize_telegram_command(payload: dict[str, Any]) -> dict[str, Any]:
    callback = payload.get("callback_query") or {}
    message = payload.get("message") or callback.get("message") or {}
    sender = payload.get("from") or message.get("from") or callback.get("from") or {}
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
