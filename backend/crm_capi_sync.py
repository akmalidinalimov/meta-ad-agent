"""Send Meta a conversion only after the CRM has judged the lead.

Why this exists. Firing a conversion the moment a phone arrives teaches Meta from a set that
turned out ~47% junk — half of what it learned in June and July was how to find people who
waste a rep's time, and the junk rate climbed 30% -> 45% -> 65% as it got better at it.

So the event moves to where the verdict is:

    phone captured  ->  CRM lead created   ->  (nothing sent to Meta yet)
    rep works it    ->  status changes     ->  QualifiedLead, if it is not junk
    payment taken   ->  paid status        ->  Purchase, with value

Both events reuse the browser identity stored at capture time (capi_bridge), looked up by
phone, so a conversion sent three weeks later still carries the fbp/fbc that ties it to the
original ad click.

Volume note: qualified runs ~210/week at current lead flow, comfortably above the ~50/week
Meta needs to learn. Purchases run ~12/week — too thin to optimize on, so send them for
measurement and as the lookalike seed, and keep the campaign optimizing on qualified.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from .capi_bridge import build_capi_event, is_matchable, lookup_identity_by_phone, send_capi_events
from .meta_client import MetaApiError, get_meta_config

ROOT = Path(__file__).resolve().parents[1]
STORAGE_DIR = ROOT / "storage"
SENT_FILENAME = "capi_sent.json"

QUALIFIED_EVENT = "QualifiedLead"
PURCHASE_EVENT = "Purchase"


def _resolve_dir(storage_dir: Path | None) -> Path:
    return storage_dir if storage_dir is not None else STORAGE_DIR


def _env_ids(name: str, default: str = "") -> set[str]:
    return {item.strip() for item in os.getenv(name, default).split(",") if item.strip()}


# --------------------------------------------------------------------------- classification


def junk_stage_ids() -> set[str]:
    return _env_ids("BITRIX_JUNK_STATUS_IDS", "JUNK")


def classify_stage(
    stage_id: str,
    *,
    paid_ids: set[str],
    junk_ids: set[str],
    qualified_ids: set[str] | None = None,
) -> str:
    """Map a Bitrix status to what, if anything, Meta should be told.

    Returns "paid", "qualified", "junk" or "unknown".

    When BITRIX_QUALIFIED_STATUS_IDS is not configured the rule is deliberately permissive:
    anything a rep did not mark junk counts as qualified. That matches the ~53% non-junk share
    and errs toward sending, because a missing conversion costs Meta more learning than a
    slightly loose definition does. Set the env var to tighten it.
    """
    stage = (stage_id or "").strip()
    if not stage:
        return "unknown"
    if stage in paid_ids:
        return "paid"
    if stage in junk_ids:
        return "junk"
    if qualified_ids:
        return "qualified" if stage in qualified_ids else "unknown"
    return "qualified"


# --------------------------------------------------------------------------- sent-state


def load_sent(*, storage_dir: Path | None = None) -> dict[str, list[str]]:
    path = _resolve_dir(storage_dir) / SENT_FILENAME
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {str(k): list(v) for k, v in data.items()} if isinstance(data, dict) else {}


def save_sent(sent: dict[str, list[str]], *, storage_dir: Path | None = None) -> None:
    directory = _resolve_dir(storage_dir)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / SENT_FILENAME).write_text(json.dumps(sent, ensure_ascii=False, indent=1), encoding="utf-8")


# --------------------------------------------------------------------------- selection


def select_pending(
    leads: list[dict[str, Any]],
    sent: dict[str, list[str]],
    *,
    paid_ids: set[str],
    junk_ids: set[str],
    qualified_ids: set[str] | None = None,
) -> list[tuple[dict[str, Any], str]]:
    """Which (lead, event) pairs still need sending.

    A lead can legitimately produce both events over its life — QualifiedLead when a rep works
    it, Purchase when it converts — so reaching paid also backfills the qualified event if it
    was never sent. Anything already sent is skipped; this is the only thing standing between a
    restart and duplicate conversions.
    """
    pending: list[tuple[dict[str, Any], str]] = []
    for lead in leads:
        lead_id = str(lead.get("crmLeadId") or "")
        if not lead_id:
            continue
        already = set(sent.get(lead_id, []))
        verdict = classify_stage(
            str(lead.get("stage") or ""), paid_ids=paid_ids, junk_ids=junk_ids, qualified_ids=qualified_ids
        )
        if verdict in ("junk", "unknown"):
            continue
        if QUALIFIED_EVENT not in already:
            pending.append((lead, QUALIFIED_EVENT))
        if verdict == "paid" and PURCHASE_EVENT not in already:
            pending.append((lead, PURCHASE_EVENT))
    return pending


def build_event_for(lead: dict[str, Any], event_name: str, *, storage_dir: Path | None = None) -> dict[str, Any]:
    phone = lead.get("phone")
    identity = lookup_identity_by_phone(phone, storage_dir=storage_dir)
    event = build_capi_event(
        event_name=event_name,
        token=(identity or {}).get("token"),
        phone=phone,
        first_name=lead.get("name") or lead.get("title"),
        identity=identity,
        aud=lead.get("utmContent") or (identity or {}).get("aud"),
        event_time=int(time.time()),
    )
    if event_name == PURCHASE_EVENT:
        value = os.getenv("META_CAPI_PURCHASE_VALUE", "").strip()
        if value:
            custom = event.setdefault("custom_data", {})
            custom["value"] = value
            custom["currency"] = os.getenv("META_CAPI_CURRENCY", "USD").strip() or "USD"
    return event


# --------------------------------------------------------------------------- orchestration


async def run_crm_capi_sync(
    leads: list[dict[str, Any]],
    *,
    paid_ids: set[str],
    junk_ids: set[str] | None = None,
    qualified_ids: set[str] | None = None,
    storage_dir: Path | None = None,
    dry_run: bool = False,
    sender=send_capi_events,
) -> dict[str, Any]:
    """Send every conversion the CRM now justifies. Safe to run repeatedly."""
    junk_ids = junk_ids if junk_ids is not None else junk_stage_ids()
    sent = load_sent(storage_dir=storage_dir)
    pending = select_pending(
        leads, sent, paid_ids=paid_ids, junk_ids=junk_ids, qualified_ids=qualified_ids
    )

    events: list[dict[str, Any]] = []
    marks: list[tuple[str, str]] = []
    matched = 0
    for lead, event_name in pending:
        event = build_event_for(lead, event_name, storage_dir=storage_dir)
        events.append(event)
        marks.append((str(lead["crmLeadId"]), event_name))
        if is_matchable(event):
            matched += 1

    result: dict[str, Any] = {
        "pending": len(pending),
        "sent": 0,
        "matched": matched,
        "unmatched": len(pending) - matched,
        "dryRun": bool(dry_run),
    }
    if not events or dry_run:
        result["events"] = events if dry_run else []
        return result

    config = get_meta_config()
    # Meta caps a batch at 1000 events; chunk so a large backlog cannot fail wholesale.
    for start in range(0, len(events), 500):
        chunk = events[start : start + 500]
        try:
            await sender(config, chunk)
        except MetaApiError as error:
            # Stop and keep the unsent marks unrecorded, so the next run retries this chunk
            # rather than silently dropping the conversions.
            result["error"] = str(error)
            save_sent(sent, storage_dir=storage_dir)
            return result
        for lead_id, event_name in marks[start : start + len(chunk)]:
            sent.setdefault(lead_id, [])
            if event_name not in sent[lead_id]:
                sent[lead_id].append(event_name)
        result["sent"] += len(chunk)

    save_sent(sent, storage_dir=storage_dir)
    return result
