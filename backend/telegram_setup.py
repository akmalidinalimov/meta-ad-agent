"""One-time Telegram bot UI registration (command menu + menu button).

Called on app startup so the bot shows a tappable command list and a menu
button instead of requiring the operator to memorise slash commands. Idempotent
— safe to call on every boot. In Phase B the menu button becomes a Web App
button pointing at the Analytics Mini App.
"""

from __future__ import annotations

import logging
from typing import Any

from .telegram_outbound import telegram_api

logger = logging.getLogger(__name__)

BOT_COMMANDS: list[dict[str, str]] = [
    {"command": "menu", "description": "Open the control menu"},
    {"command": "kpis", "description": "Latest KPI table"},
    {"command": "suggestions", "description": "Pending suggestions to review"},
    {"command": "status", "description": "Connection + queue status"},
    {"command": "alerts", "description": "Monitoring alerts"},
    {"command": "help", "description": "What I can do"},
]


def register_bot_ui() -> dict[str, Any]:
    """Register the command list + menu button with Telegram. Returns the API
    results (never raises)."""
    results: dict[str, Any] = {}
    results["setMyCommands"] = telegram_api("setMyCommands", {"commands": BOT_COMMANDS})
    # MVP: a "commands" menu button opens the command list. Phase B swaps this
    # for a web_app button that opens the Analytics Mini App.
    results["setChatMenuButton"] = telegram_api("setChatMenuButton", {"menu_button": {"type": "commands"}})
    return results
