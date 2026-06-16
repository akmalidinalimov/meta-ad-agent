from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .crm_store import list_crm_leads

ROOT = Path(__file__).resolve().parents[1]
STORAGE_DIR = ROOT / "storage"
FUNNEL_EVENTS_PATH = STORAGE_DIR / "funnel_events.jsonl"

FIELD_MAP = {
    "event_name": "eventName",
    "eventName": "eventName",
    "visitor_id": "visitorId",
    "visitorId": "visitorId",
    "telegram_user_id": "telegramUserId",
    "telegramUserId": "telegramUserId",
    "telegram_username": "telegramUsername",
    "telegramUsername": "telegramUsername",
    "telegram_full_name": "telegramFullName",
    "telegramFullName": "telegramFullName",
    "segment": "segment",
    "vsl_id": "vslId",
    "vslId": "vslId",
    "landing_page_id": "landingPageId",
    "landingPageId": "landingPageId",
    "telegram_bot_id": "telegramBotId",
    "telegramBotId": "telegramBotId",
    "campaign_id": "campaignId",
    "campaignId": "campaignId",
    "adset_id": "adSetId",
    "adSetId": "adSetId",
    "ad_id": "adId",
    "adId": "adId",
    "creative_id": "creativeId",
    "creativeId": "creativeId",
    "utm_source": "utmSource",
    "utm_medium": "utmMedium",
    "utm_campaign": "utmCampaign",
    "utm_content": "utmContent",
    "utm_term": "utmTerm",
    "fbclid": "fbclid",
    "value_usd": "valueUsd",
    "valueUsd": "valueUsd",
}

CANONICAL_EVENTS = {
    "landing_view",
    "vsl_button_click",
    "telegram_link_click",
    "bot_start",
    "vsl_sequence_started",
    "vsl_key_message_sent",
    "form_button_click",
    "form_opened",
    "crm_form_submit",
    "qualified_lead",
    "partial_payment",
    "full_payment",
}

EVENT_NAME_PATTERN = re.compile(r"[^a-z0-9_]+")


def normalize_funnel_event(payload: dict[str, Any]) -> dict[str, Any]:
    event: dict[str, Any] = {
        "id": payload.get("id") or f"evt_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}",
        "receivedAt": datetime.now(timezone.utc).isoformat(),
    }
    for source, target in FIELD_MAP.items():
        value = payload.get(source)
        if value not in (None, ""):
            event[target] = value
    event["eventName"] = normalize_event_name(event.get("eventName"))
    event["raw"] = {key: value for key, value in payload.items() if key not in FIELD_MAP}
    return event


def save_funnel_event(payload: dict[str, Any], *, storage_dir: Path = STORAGE_DIR) -> dict[str, Any]:
    event = normalize_funnel_event(payload)
    path = storage_dir / "funnel_events.jsonl"
    storage_dir.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def load_funnel_events(*, storage_dir: Path = STORAGE_DIR) -> list[dict[str, Any]]:
    path = storage_dir / "funnel_events.jsonl"
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def count_event_users(event_name: str, *, since_iso: str | None = None, storage_dir: Path = STORAGE_DIR) -> int:
    """Unique users who fired ``event_name``, deduplicated by Telegram user (falling
    back to visitor id). Optionally limited to events received on/after ``since_iso``.

    Deduplicating by user means a person who repeats the same event is counted once,
    so any rate built on these counts can't be inflated by repeats.
    """
    users: set[str] = set()
    for event in load_funnel_events(storage_dir=storage_dir):
        if event.get("eventName") != event_name:
            continue
        if since_iso and str(event.get("receivedAt") or "") < since_iso:
            continue
        identity = event.get("telegramUserId") or event.get("visitorId")
        if identity:
            users.add(str(identity))
    return len(users)


def count_bot_starts(*, since_iso: str | None = None, storage_dir: Path = STORAGE_DIR) -> int:
    """Unique Telegram bot starts — the START-rate numerator. See count_event_users."""
    return count_event_users("bot_start", since_iso=since_iso, storage_dir=storage_dir)


def select_start_rate(*, bot_starts: int, subscribes: int, link_clicks: int, leads: int) -> dict[str, Any]:
    """Compute the dashboard START rate from the cleanest available signals, capped 100%.

    Numerator: first-party deduped bot starts; falls back to Meta 'subscribe'
    conversions only when there are no relay events.
    Denominator: first-party Telegram-button clicks (``telegram_link_click``) when
    available — the operator's true "of those who clicked to Telegram, how many
    started" — falling back to Meta 'leads' while the landing-page tracker isn't
    firing yet. This keeps START rate independent of lead rate whenever the
    first-party signal exists, and degrades honestly otherwise.

    Returns {rate, numerator, denominator, numeratorSource, denominatorSource}.
    """
    numerator = bot_starts if bot_starts else subscribes
    numerator_source = "telegram_relay" if bot_starts else ("meta_subscribe" if subscribes else "none")
    if link_clicks:
        denominator, denominator_source = link_clicks, "telegram_link_click"
    elif leads:
        denominator, denominator_source = leads, "meta_leads"
    else:
        denominator, denominator_source = 0, "none"
    rate = min(100.0, (numerator / denominator * 100) if denominator else 0.0)
    return {
        "rate": round(rate, 1),
        "numerator": numerator,
        "denominator": denominator,
        "numeratorSource": numerator_source,
        "denominatorSource": denominator_source,
    }


def telegram_starts_by_campaign_date(*, storage_dir: Path = STORAGE_DIR) -> dict[tuple[str, str], int]:
    """Count Telegram START (bot_start) events per (campaignId, date).

    This is the join key that lets ingested funnel events feed the per-(campaign, date)
    metric rows the dashboard and 4-hourly monitoring consume. The date is taken from
    each event's receivedAt as UTC YYYY-MM-DD, which matches the Meta insight rows'
    date_start format used in dashboard_service.map_metric_row.

    Caveat: receivedAt is UTC while Meta date_start is in the ad-account timezone, so a
    START near local midnight can land one day off. Accepted for now; a future
    FUNNEL_EVENT_TZ_OFFSET_HOURS knob can correct it. Only events carrying a campaignId
    are counted so each START attaches to a specific campaign's row; un-attributed
    starts are intentionally dropped here (they cannot be joined).
    """
    counts: Counter[tuple[str, str]] = Counter()
    for event in load_funnel_events(storage_dir=storage_dir):
        if event.get("eventName") != "bot_start":
            continue
        campaign_id = event.get("campaignId")
        date = str(event.get("receivedAt") or "")[:10]
        if not campaign_id or not date:
            continue
        counts[(str(campaign_id), date)] += 1
    return dict(counts)


def build_funnel_summary(*, storage_dir: Path = STORAGE_DIR) -> dict[str, Any]:
    events = load_funnel_events(storage_dir=storage_dir)
    by_name = Counter(event.get("eventName", "unknown") for event in events)
    by_segment: dict[str, Counter[str]] = defaultdict(Counter)
    visitors = set()
    telegram_users = set()
    visitors_by_event: dict[str, set[str]] = defaultdict(set)
    event_steps: list[dict[str, Any]] = []
    crm = build_crm_summary(storage_dir=storage_dir)

    for event in events:
        event_name = event.get("eventName", "unknown")
        segment = str(event.get("segment") or "unknown")
        by_segment[segment][event_name] += 1
        if event_name not in [step["eventName"] for step in event_steps]:
            event_steps.append({"eventName": event_name, "count": 0, "uniqueVisitors": 0, "rateFromPrevious": None})
        if event.get("visitorId"):
            visitor_id = str(event["visitorId"])
            visitors.add(visitor_id)
            visitors_by_event[event_name].add(visitor_id)
        if event.get("telegramUserId"):
            telegram_users.add(str(event["telegramUserId"]))

    for step in event_steps:
        step["count"] = by_name[step["eventName"]]
        step["uniqueVisitors"] = len(visitors_by_event[step["eventName"]])
    for index, step in enumerate(event_steps):
        if index > 0:
            previous = event_steps[index - 1]
            step["rateFromPrevious"] = min(100, rate(step["uniqueVisitors"], previous["uniqueVisitors"]))

    return {
        "totalEvents": len(events),
        "eventsByName": dict(by_name),
        "eventsBySegment": {segment: dict(counter) for segment, counter in by_segment.items()},
        "uniqueVisitors": len(visitors),
        "uniqueTelegramUsers": len(telegram_users),
        "latestEventAt": events[-1].get("receivedAt") if events else None,
        "eventSteps": event_steps,
        "rates": {
            "telegramStartRate": visitor_rate(visitors_by_event, "bot_start", "telegram_link_click"),
            "keyMessageReachRate": visitor_rate(visitors_by_event, "vsl_key_message_sent", "bot_start"),
            "formClickRate": visitor_rate(visitors_by_event, "form_button_click", "vsl_key_message_sent"),
            "qualifiedLeadRate": visitor_rate(visitors_by_event, "qualified_lead", "form_button_click"),
            "fullPaymentRate": visitor_rate(visitors_by_event, "full_payment", "qualified_lead"),
            "crmAttributedLeadRate": rate(crm["attributedLeads"], len(visitors_by_event["form_button_click"])),
        },
        "crm": crm,
    }


def build_crm_summary(*, storage_dir: Path = STORAGE_DIR) -> dict[str, Any]:
    leads = list_crm_leads(storage_dir=storage_dir)
    events = load_funnel_events(storage_dir=storage_dir)
    known_visitors = {str(event.get("visitorId")) for event in events if event.get("visitorId")}
    known_telegram_users = {str(event.get("telegramUserId")) for event in events if event.get("telegramUserId")}
    stages = Counter(str(lead.get("stage") or "unknown") for lead in leads)
    attributed = [
        lead
        for lead in leads
        if (lead.get("visitorId") and str(lead["visitorId"]) in known_visitors)
        or (lead.get("telegramUserId") and str(lead["telegramUserId"]) in known_telegram_users)
    ]
    return {
        "totalLeads": len(leads),
        "attributedLeads": len(attributed),
        "stages": dict(stages),
    }


def rate(value: int | float, previous: int | float) -> float:
    return 0 if not previous else round((value / previous) * 100, 2)


def visitor_rate(visitors_by_event: dict[str, set[str]], event_name: str, previous_event_name: str) -> float:
    return min(100, rate(len(visitors_by_event[event_name]), len(visitors_by_event[previous_event_name])))


def normalize_event_name(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = EVENT_NAME_PATTERN.sub("_", text).strip("_")
    text = re.sub(r"_+", "_", text)
    return text[:80] if text else "unknown"
