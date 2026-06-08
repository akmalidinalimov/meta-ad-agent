"""Telegram inline menus and welcome copy.

The bot's main control surface: a button grid the operator taps instead of
typing slash commands. Buttons carry callback_data `menu:<target>` which
routers/telegram.py dispatches.
"""

from __future__ import annotations

from typing import Any


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
