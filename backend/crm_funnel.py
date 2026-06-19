from __future__ import annotations

import re
from typing import Any, Iterable

# Audiences we split by (match the ChatPlace src_<aud> tags / referral-link aud values).
KNOWN_AUDIENCES = ("ai", "business", "it", "original", "content")

# Substrings that identify a terminal "Paid"/"Won" stage when BITRIX_PAID_STATUS_IDS is
# not configured. Matched case-insensitively against the stage id AND label, in Uzbek /
# Russian / English. This is only a rough default — the sales team should confirm the real
# Paid stage(s) and set BITRIX_PAID_STATUS_IDS, which always wins over this heuristic.
PAID_NAME_KEYWORDS = ("paid", "to'l", "to‘l", "to’l", "оплач", "оплат", "won", "sotil", "купил", "успешн")

_DIGITS = re.compile(r"\D+")


def normalize_phone(value: Any) -> str:
    """Canonical phone match key: the trailing 9 digits (the UZ subscriber number).

    Robust to '+998', '998', leading '0', spaces, and bare local numbers, so ChatPlace
    and Bitrix formats join cleanly without country-code mismatches.
    """
    digits = _DIGITS.sub("", str(value or ""))
    if not digits:
        return ""
    return digits[-9:] if len(digits) >= 9 else digits


def normalize_username(value: Any) -> str:
    text = str(value or "").strip().lstrip("@").lower()
    if "t.me/" in text:
        text = text.split("t.me/", 1)[1].strip("/")
    return text


def normalize_aud(value: Any) -> str:
    text = str(value or "").strip().lower()
    for prefix in ("src_", "vsl_"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text


def build_audience_index(events: Iterable[dict[str, Any]]) -> dict[str, dict[str, str]]:
    """phone->aud and username->aud lookup maps built from funnel events.

    First-seen audience wins (setdefault), so a later audience-less duplicate start can
    never erase the audience captured at the original bot start.
    """
    by_phone: dict[str, str] = {}
    by_username: dict[str, str] = {}
    for event in events:
        aud = normalize_aud(event.get("aud") or event.get("segment"))
        if aud not in KNOWN_AUDIENCES:
            continue
        phone = normalize_phone(event.get("phone"))
        if phone:
            by_phone.setdefault(phone, aud)
        username = normalize_username(event.get("telegramUsername"))
        if username:
            by_username.setdefault(username, aud)
    return {"byPhone": by_phone, "byUsername": by_username}


def count_bot_starts_by_audience(events: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Unique bot starts per audience, deduped by Telegram user (then phone, then visitor)."""
    seen: dict[str, set[str]] = {aud: set() for aud in KNOWN_AUDIENCES}
    for event in events:
        if event.get("eventName") != "bot_start":
            continue
        aud = normalize_aud(event.get("aud") or event.get("segment"))
        if aud not in KNOWN_AUDIENCES:
            continue
        identity = event.get("telegramUserId") or normalize_phone(event.get("phone")) or event.get("visitorId")
        if identity:
            seen[aud].add(str(identity))
    return {aud: len(ids) for aud, ids in seen.items()}


def resolve_paid_stage_ids(stages: list[dict[str, Any]], *, configured_ids: list[str] | None = None) -> set[str]:
    """Stage ids that count as 'Paid'. Explicit config (BITRIX_PAID_STATUS_IDS) wins;
    otherwise fall back to a label-keyword heuristic. May be empty (paid stage unknown)."""
    if configured_ids:
        configured = {s.strip() for s in configured_ids if s and s.strip()}
        if configured:
            return configured
    paid: set[str] = set()
    for stage in stages:
        haystack = f"{stage.get('id') or ''} {stage.get('name') or ''}".lower()
        if any(keyword in haystack for keyword in PAID_NAME_KEYWORDS):
            paid.add(str(stage.get("id")))
    return paid


def _join_audience(record: dict[str, Any], by_phone: dict[str, str], by_username: dict[str, str]) -> str:
    """Phone-join (primary) -> @username (secondary) -> utm_content cross-check (fallback)."""
    phone = normalize_phone(record.get("phone"))
    if phone and phone in by_phone:
        return by_phone[phone]
    username = normalize_username(record.get("telegramUsername"))
    if username and username in by_username:
        return by_username[username]
    aud = normalize_aud(record.get("utmContent"))
    return aud if aud in KNOWN_AUDIENCES else ""


# --- Cell A / Cell B attribution (Telegram-bot form vs the same form used elsewhere) ----
# Cell B = the Telegram-bot VSL landing form. Bitrix tags those leads with a SOURCE_DESCRIPTION
# like "Landing B (VSL embed)" (and/or utm_content "cellb"). Everything else is Cell A. The
# tags are configurable (BITRIX_BOT_SOURCE_DESCRIPTION / BITRIX_BOT_UTM_CONTENT) since the
# marker is set upstream and may change.
DEFAULT_BOT_SOURCE_DESCRIPTIONS = ("landing b",)
DEFAULT_BOT_UTM_CONTENTS = ("cellb",)


def lead_cell(
    record: dict[str, Any],
    *,
    bot_source_descriptions: Iterable[str] = DEFAULT_BOT_SOURCE_DESCRIPTIONS,
    bot_utm_contents: Iterable[str] = DEFAULT_BOT_UTM_CONTENTS,
) -> str:
    """Classify a normalized Bitrix lead as Cell 'B' (Telegram-bot VSL form) or 'A' (other).

    Cell B when SOURCE_DESCRIPTION contains any configured bot tag (case-insensitive
    substring, e.g. 'landing b') OR utm_content equals a configured bot tag (e.g. 'cellb').
    """
    source_desc = str(record.get("sourceDescription") or "").lower()
    utm_content = str(record.get("utmContent") or "").strip().lower()
    descs = [d.strip().lower() for d in bot_source_descriptions if d and d.strip()]
    utms = {u.strip().lower() for u in bot_utm_contents if u and u.strip()}
    if (descs and any(tag in source_desc for tag in descs)) or (utm_content and utm_content in utms):
        return "B"
    return "A"


def split_by_cell(
    records: list[dict[str, Any]],
    *,
    bot_source_descriptions: Iterable[str] = DEFAULT_BOT_SOURCE_DESCRIPTIONS,
    bot_utm_contents: Iterable[str] = DEFAULT_BOT_UTM_CONTENTS,
) -> dict[str, list[dict[str, Any]]]:
    """Partition normalized leads into {'A': [...], 'B': [...]} by lead_cell."""
    out: dict[str, list[dict[str, Any]]] = {"A": [], "B": []}
    descs = list(bot_source_descriptions)
    utms = list(bot_utm_contents)
    for record in records:
        cell = lead_cell(record, bot_source_descriptions=descs, bot_utm_contents=utms)
        out[cell].append(record)
    return out


def build_crm_stage_breakdown(
    records: list[dict[str, Any]],
    *,
    stages: list[dict[str, Any]],
    paid_status_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Overall stage distribution (no audience split) for a filtered set of leads —
    e.g. only the 'AI Creators 5.0 buyurtmasi' order leads. Returns ordered stages with
    counts, the total, and the Paid count."""
    stage_ids = [str(s.get("id")) for s in stages if str(s.get("id") or "")]
    stage_labels = {str(s.get("id")): str(s.get("name") or s.get("id")) for s in stages}
    counts = {sid: 0 for sid in stage_ids}
    total = 0
    for record in records:
        sid = str(record.get("stage") or "")
        if not sid:
            continue
        total += 1
        if sid not in counts:
            counts[sid] = 0
            stage_ids.append(sid)
            stage_labels.setdefault(sid, sid)
        counts[sid] += 1
    paid_ids = resolve_paid_stage_ids(
        [{"id": sid, "name": stage_labels[sid]} for sid in stage_ids], configured_ids=paid_status_ids
    )
    paid = sum(count for sid, count in counts.items() if sid in paid_ids)
    return {
        "total": total,
        "paid": paid,
        "paidStageIds": sorted(paid_ids),
        "stages": [{"id": sid, "name": stage_labels[sid], "count": counts[sid]} for sid in stage_ids],
    }


def build_crm_funnel(
    records: list[dict[str, Any]],
    *,
    stages: list[dict[str, Any]],
    events: list[dict[str, Any]],
    paid_status_ids: list[str] | None = None,
    days: int | None = None,
    source: str = "bitrix",
    refreshed_at: str = "",
) -> dict[str, Any]:
    """Per-audience x per-stage matrix. records are normalized Bitrix leads/deals
    (each carrying 'stage', 'phone', 'telegramUsername', 'utmContent')."""
    index = build_audience_index(events)
    by_phone, by_username = index["byPhone"], index["byUsername"]
    bot_starts = count_bot_starts_by_audience(events)

    stage_ids = [str(s.get("id")) for s in stages if str(s.get("id") or "")]
    stage_labels = {str(s.get("id")): str(s.get("name") or s.get("id")) for s in stages}
    for record in records:  # append any stage seen on records but missing from discovery
        sid = str(record.get("stage") or "")
        if sid and sid not in stage_ids:
            stage_ids.append(sid)
            stage_labels.setdefault(sid, sid)

    paid_ids = resolve_paid_stage_ids(
        [{"id": sid, "name": stage_labels[sid]} for sid in stage_ids], configured_ids=paid_status_ids
    )

    buckets = list(KNOWN_AUDIENCES) + ["unattributed"]
    rows = {aud: {sid: 0 for sid in stage_ids} for aud in buckets}

    matched = 0
    total = 0
    for record in records:
        sid = str(record.get("stage") or "")
        if not sid:
            continue
        total += 1
        aud = _join_audience(record, by_phone, by_username)
        if aud in KNOWN_AUDIENCES:
            matched += 1
        else:
            aud = "unattributed"
        rows[aud][sid] = rows[aud].get(sid, 0) + 1

    audiences: dict[str, Any] = {}
    for aud in buckets:
        counts = rows[aud]
        submits = sum(counts.values())
        paid = sum(count for sid, count in counts.items() if sid in paid_ids)
        starts = bot_starts.get(aud, 0)
        entry: dict[str, Any] = dict(counts)
        entry["submits"] = submits
        entry["paid"] = paid
        entry["botStarts"] = starts
        entry["paidRate"] = round(paid / submits, 4) if submits else 0.0
        entry["paidRatePerStart"] = round(paid / starts, 4) if starts else 0.0
        audiences[aud] = entry

    return {
        "range": {"days": days},
        "stages": stage_ids,
        "stageLabels": stage_labels,
        "paidStageIds": sorted(paid_ids),
        "audiences": audiences,
        "matchRate": round(matched / total, 4) if total else 0.0,
        "source": source,
        "refreshedAt": refreshed_at,
    }
