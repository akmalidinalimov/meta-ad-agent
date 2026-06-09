from __future__ import annotations

import asyncio
import json
import os
import ssl
import urllib.error
import urllib.request
from typing import Any

from dotenv import load_dotenv

load_dotenv()


def build_approval_notification(approval: dict[str, Any]) -> dict[str, Any]:
    campaign = approval.get("after", {}).get("campaign", {})
    adsets = approval.get("after", {}).get("adsets", [])
    total_budget = sum(float(adset.get("daily_budget") or 0) / 100 for adset in adsets)
    text = "\n".join(
        [
            "Meta Agent approval request",
            f"Campaign: {campaign.get('name', approval.get('actionType', 'Unknown action'))}",
            f"Status: {approval.get('status')} / guardrail: {approval.get('guardrailResult')}",
            f"Paused ad sets: {len(adsets)}",
            f"Daily budget: ${total_budget:,.2f}",
            f"Risk: {approval.get('risk')}",
            "",
            "Approving records permission only. Publishing or spend still requires execution guardrails.",
        ]
    )
    return {
        "text": text,
        "reply_markup": {
            "inline_keyboard": [
                [
                    {"text": "Approve", "callback_data": f"approve:{approval.get('id')}"},
                    {"text": "Reject", "callback_data": f"reject:{approval.get('id')}"},
                ],
                [
                    {"text": "Needs changes", "callback_data": f"changes:{approval.get('id')}"},
                    {"text": "Open dashboard", "callback_data": f"view:{approval.get('id')}"},
                ],
            ]
        },
    }


def send_approval_notification(approval: dict[str, Any]) -> dict[str, Any]:
    notification = build_approval_notification(approval)
    return send_telegram_message_sync(
        notification["text"],
        reply_markup=notification["reply_markup"],
    )


def send_telegram_message_sync(text: str, **kwargs: Any) -> dict[str, Any]:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = str(kwargs.pop("chat_id", "") or os.getenv("TELEGRAM_ADMIN_CHAT_ID", "")).strip()
    if not token or not chat_id:
        return {"ok": False, "skipped": True, "error": "Telegram bot token or admin chat ID is not configured."}

    payload = {
        "chat_id": chat_id,
        "text": text,
        **kwargs,
    }
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15, context=ssl_context()) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.URLError as error:
        return {"ok": False, "skipped": False, "error": str(error)}

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"ok": False, "skipped": False, "error": "Telegram returned a non-JSON response."}


async def send_telegram_message(text: str, **kwargs: Any) -> dict[str, Any]:
    # Offload the blocking urllib call to a thread so it never stalls the event loop.
    return await asyncio.to_thread(send_telegram_message_sync, text, **kwargs)


def telegram_api(method: str, payload: dict[str, Any], *, timeout: int = 15) -> dict[str, Any]:
    """Call any Telegram Bot API method (setMyCommands, setChatMenuButton,
    answerCallbackQuery, editMessageText, sendPhoto, sendVideo, ...). Returns the
    parsed JSON or an error dict; never raises."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return {"ok": False, "skipped": True, "error": "Telegram bot token is not configured."}

    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=ssl_context()) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.URLError as error:
        return {"ok": False, "skipped": False, "error": str(error)}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"ok": False, "skipped": False, "error": "Telegram returned a non-JSON response."}


def send_photo(
    chat_id: Any,
    photo: str,
    *,
    caption: str | None = None,
    parse_mode: str | None = None,
    reply_markup: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Send an image by URL so a creative thumbnail renders inline in the chat."""
    if not chat_id or not photo:
        return {"ok": False, "skipped": True}
    payload: dict[str, Any] = {"chat_id": chat_id, "photo": photo}
    if caption:
        payload["caption"] = caption
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return telegram_api("sendPhoto", payload, timeout=30)


def send_video(
    chat_id: Any,
    video: str,
    *,
    caption: str | None = None,
    parse_mode: str | None = None,
    reply_markup: dict[str, Any] | None = None,
    supports_streaming: bool = True,
) -> dict[str, Any]:
    """Send a video by URL so the creative plays inline (tap to watch)."""
    if not chat_id or not video:
        return {"ok": False, "skipped": True}
    payload: dict[str, Any] = {"chat_id": chat_id, "video": video, "supports_streaming": supports_streaming}
    if caption:
        payload["caption"] = caption
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    # Telegram downloads the remote video before responding, so allow extra time.
    return telegram_api("sendVideo", payload, timeout=45)


def edit_message_reply_markup(chat_id: Any, message_id: Any, reply_markup: dict[str, Any]) -> dict[str, Any]:
    """Update the inline buttons on an existing message (the apply-flow lifecycle)."""
    if not chat_id or not message_id:
        return {"ok": False, "skipped": True}
    return telegram_api(
        "editMessageReplyMarkup",
        {"chat_id": chat_id, "message_id": message_id, "reply_markup": reply_markup or {"inline_keyboard": []}},
    )


def edit_message_text(
    chat_id: Any,
    message_id: Any,
    text: str,
    reply_markup: dict[str, Any] | None = None,
    parse_mode: str | None = None,
) -> dict[str, Any]:
    """Replace an existing message's text (and optionally its inline buttons).

    Used by the in-place drill-down navigation so tapping a button rewrites the
    same message instead of spamming the chat with new ones.
    """
    if not chat_id or not message_id:
        return {"ok": False, "skipped": True}
    payload: dict[str, Any] = {"chat_id": chat_id, "message_id": message_id, "text": text}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    if parse_mode:
        payload["parse_mode"] = parse_mode
    return telegram_api("editMessageText", payload)


def answer_callback_query(callback_query_id: str | None, text: str | None = None) -> dict[str, Any]:
    """Acknowledge a button tap so Telegram stops the loading spinner."""
    if not callback_query_id:
        return {"ok": False, "skipped": True}
    payload: dict[str, Any] = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    return telegram_api("answerCallbackQuery", payload)


def ssl_context() -> ssl.SSLContext | None:
    try:
        import truststore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        pass
    try:
        import certifi
    except ImportError:
        return None
    return ssl.create_default_context(cafile=certifi.where())
