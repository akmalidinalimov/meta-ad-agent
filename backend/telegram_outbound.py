from __future__ import annotations

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
    return send_telegram_message_sync(text, **kwargs)


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
