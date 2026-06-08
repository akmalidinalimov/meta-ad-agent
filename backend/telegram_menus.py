"""Telegram inline menus and welcome copy.

The bot's main control surface: a button grid the operator taps instead of
typing slash commands. Buttons carry callback_data `menu:<target>` which
routers/telegram.py dispatches.
"""

from __future__ import annotations

from typing import Any


# Labels for the persistent reply keyboard (docked under the text input). Tapping
# one sends its label as a normal message, which routers/telegram.py maps to an action.
BTN_KPIS = "📊 KPIs"
BTN_SUGGESTIONS = "🤖 Suggestions"
BTN_STATUS = "📈 Status"
BTN_ALERTS = "🚨 Alerts"
BTN_ASK = "💬 Ask the agent"
BTN_ANALYTICS = "📊 Analytics"

# label (lowercased) -> menu action target handled by _handle_menu.
REPLY_BUTTON_ACTIONS: dict[str, str] = {
    BTN_KPIS.lower(): "kpis",
    BTN_SUGGESTIONS.lower(): "suggestions",
    BTN_STATUS.lower(): "status",
    BTN_ALERTS.lower(): "alerts",
    BTN_ASK.lower(): "chat",
    BTN_ANALYTICS.lower(): "analytics",
}


def main_reply_keyboard() -> dict[str, Any]:
    """Persistent buttons docked under the message input (always visible)."""
    return {
        "keyboard": [
            [{"text": BTN_KPIS}, {"text": BTN_SUGGESTIONS}],
            [{"text": BTN_STATUS}, {"text": BTN_ALERTS}],
            [{"text": BTN_ASK}, {"text": BTN_ANALYTICS}],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
    }


def main_menu_keyboard() -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "📊 KPIs", "callback_data": "menu:kpis"},
                {"text": "🤖 Suggestions", "callback_data": "menu:suggestions"},
            ],
            [
                {"text": "📈 Status", "callback_data": "menu:status"},
                {"text": "🚨 Alerts", "callback_data": "menu:alerts"},
            ],
            [
                {"text": "💬 Ask the agent", "callback_data": "menu:chat"},
                {"text": "📊 Analytics", "callback_data": "menu:analytics"},
            ],
        ]
    }


def welcome_text() -> str:
    return (
        "👋 <b>Meta Ad Agent — control center</b>\n\n"
        "Tap a button below, or just text me a question "
        "(e.g. <i>which audience should I scale and why?</i>).\n\n"
        "I watch your account every 4 hours and send a KPI table here; "
        "new suggestions arrive with Approve buttons."
    )
