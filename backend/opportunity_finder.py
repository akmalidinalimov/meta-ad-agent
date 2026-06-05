"""Proactive opportunity engine (WS-E).

On a daily schedule this composes the already-built pieces into an approval-ready
"opportunity": a PAUSED test campaign for the top-3 next audiences, with the
account's winning config mirrored and recommended creatives attached. The result
is persisted as an approval the operator can one-tap Approve, and pushed to
Telegram + the web queue.

SUGGEST-ONLY: nothing here ever calls a live/execute Meta path. Every produced
approval carries ``status == "needs_review"`` (or "blocked" when guardrails fail)
and ``source == "proactive"``. ``META_LIVE_WRITES_ENABLED`` is never read here.

Determinism / testability:
- No ``datetime.now`` at import time. The "today" used for the dedup id and the
  run timestamp is injectable via ``today=`` so tests are reproducible.
- Storage dir is injectable (mirrors monitoring_scheduler) so tests never touch
  the real on-disk stores.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from .analysis_engine import rank_audiences_for_next_campaign
from .creative_recommender import build_recommended_creatives, generate_creative_angle_briefs
from .draft_campaign_proposal import select_source_template
from .meta_execution import build_campaign_creation_approval
from .strategy_generator import generate_launch_strategy

try:  # Optional persistence/notify side-effects degrade gracefully if unavailable.
    from .approval_store import STORAGE_DIR, create_approval_request
except Exception:  # pragma: no cover - defensive import guard
    from pathlib import Path as _Path

    STORAGE_DIR = _Path(__file__).resolve().parents[1] / "storage"  # type: ignore[assignment]
    create_approval_request = None  # type: ignore[assignment]

from .storage_io import read_json, write_json_atomic

KnowledgeLoader = Callable[[], dict[str, Any] | None]
PlaybookLoader = Callable[[], list[dict[str, Any]]]
AlertSender = Callable[[dict[str, Any]], dict[str, Any]]

DEFAULT_ACCOUNT_ID = "unconfigured_ad_account"
DEFAULT_PER_SEGMENT_BUDGET_USD = 100.0
RUNS_FILENAME = "opportunity_runs.json"


# ---------------------------------------------------------------------------
# Packet generation
# ---------------------------------------------------------------------------


def generate_opportunity_packets(
    knowledge: dict[str, Any] | None,
    playbooks: list[dict[str, Any]] | None,
    *,
    account_id: str | None = None,
    per_segment_budget_usd: float | None = None,
    today: date | datetime | None = None,
) -> list[dict[str, Any]]:
    """Compose the top-3 next audiences into approval-shaped opportunity packets.

    Returns a list of approval-shaped dicts. For v1 there is a single kind of
    packet ("new audience test"), but the list shape lets more kinds be added
    later without changing callers. Returns ``[]`` defensively when there is no
    knowledge base or no usable next audience to test.
    """
    analysis = (knowledge or {}).get("analysis", {}) or {}
    if not analysis:
        return []

    account = account_id or DEFAULT_ACCOUNT_ID
    budget = float(per_segment_budget_usd or DEFAULT_PER_SEGMENT_BUDGET_USD)
    day = _as_date(today)

    # Exclude interests already used by recent playbooks so we keep suggesting NEW
    # audiences rather than re-proposing what was just tested.
    exclude_labels = _recent_labels(playbooks)
    audiences = rank_audiences_for_next_campaign(analysis, exclude_labels=exclude_labels, n=3)
    if not audiences:
        return []

    # Build a playbook DIRECTLY from the ranked audiences (instead of from chat),
    # then run the same strategy + draft-proposal machinery the operator path uses.
    playbook = _playbook_from_audiences(audiences, budget=budget, today=day)
    strategy = generate_launch_strategy(playbook, knowledge)
    source_template = select_source_template(analysis)
    template_config = source_template.get("config") if source_template else None

    approval = build_campaign_creation_approval(
        playbook,
        account_id=account,
        reason=(
            "Proactive suggestion: a PAUSED test campaign for the top next audiences. "
            "Review only — do not publish or spend."
        ),
        knowledge=knowledge,
        template=template_config,
    )

    segment_labels = [segment["name"] for segment in strategy.get("segments", [])]
    creatives = build_recommended_creatives(analysis, segment_labels)

    packet = _attach_opportunity_contract(
        approval,
        day=day,
        audiences=audiences,
        creatives=creatives,
        source_template=source_template,
        excluded_labels=exclude_labels,
    )
    return [packet]


def _attach_opportunity_contract(
    approval: dict[str, Any],
    *,
    day: date,
    audiences: list[dict[str, Any]],
    creatives: list[dict[str, Any]],
    source_template: dict[str, Any] | None,
    excluded_labels: list[str],
) -> dict[str, Any]:
    """Attach the shared WS-F contract to a campaign-creation approval.

    The frontend (WS-F) reads exactly these keys — do not rename them. ``status``
    is forced to "needs_review" unless guardrails hard-failed (then it stays
    "blocked"), so a proactive packet is never accidentally execution-eligible.
    """
    approval["id"] = opportunity_approval_id(day)
    approval["source"] = "proactive"
    if approval.get("guardrailResult") != "fail":
        approval["status"] = "needs_review"
    approval["kind"] = "new_audience_test"
    approval["opportunity"] = {
        "rationale": _opportunity_rationale(audiences),
        "audiences": audiences,
        "creatives": creatives,
        "sourceTemplate": source_template,
        "excludedRecentlyTested": excluded_labels,
        "generatedFor": day.isoformat(),
    }
    return approval


def _playbook_from_audiences(
    audiences: list[dict[str, Any]],
    *,
    budget: float,
    today: date,
) -> dict[str, Any]:
    """Build a playbook whose segments ARE the ranked top-3 audiences.

    Each ranked audience becomes a test segment carrying its label as both name
    and interest, so the downstream strategy + draft builder treat it as a fresh,
    tracking-incomplete test (ABO, broad geo/age) — never as a proven scale-up.
    """
    now = datetime.now(timezone.utc).isoformat()
    segments = [
        _segment_from_audience(audience, index, budget)
        for index, audience in enumerate(audiences)
    ]
    return {
        "id": f"pb_proactive_{today.strftime('%Y%m%d')}",
        "name": "Proactive next-audience test",
        "goal": (
            "Test the highest-quality untested audiences next, optimizing toward "
            "Telegram START and downstream buyer quality."
        ),
        "primarySuccessMetric": "telegram_start",
        "secondarySuccessMetrics": ["crm_form_submit", "qualified_lead", "purchase"],
        "segments": segments,
        "rules": {
            "startingBudgetUsd": budget,
            # Headroom so the guardrail max-budget check passes for a 3-segment test
            # (mirrors the chat planner's max = start * segments * 3 heuristic).
            "maxDailyBudgetUsd": max(500.0, budget * max(1, len(segments)) * 3),
            "scalingStepPercent": 20,
            "scalingFrequencyDays": 1,
            "salesCapacityLeadsPerDay": 200,
            "requiresApprovalForExecution": True,
        },
        "alertChannels": ["dashboard", "telegram"],
        "approvalChannels": ["dashboard", "telegram"],
        "createdAt": now,
        "updatedAt": now,
    }


def _segment_from_audience(audience: dict[str, Any], index: int, budget: float) -> dict[str, Any]:
    label = str(audience.get("label") or f"Audience {index + 1}")
    interests = [str(i) for i in (audience.get("interests") or [label]) if i]
    locations = audience.get("locations") or ["Uzbekistan"]
    return {
        "id": _slug(label) or f"audience_{index + 1}",
        "name": label,
        "description": str(audience.get("rationale") or ""),
        # Intentionally no landing/telegram links: this is a fresh test, so strategy
        # marks it tracking-incomplete (ABO) rather than a proven scale candidate.
        "targetAudienceNotes": str(audience.get("rationale") or ""),
        "offerAngle": "Watch the free AI income video and enter the Telegram funnel.",
        "startingBudgetUsd": budget,
        "locations": list(locations),
        "placements": ["instagram_reels", "instagram_stories", "instagram_feed"],
        "interests": interests,
        "ageRange": audience.get("ageRange") or "23-44",
        "gender": audience.get("gender") or "all",
    }


def _opportunity_rationale(audiences: list[dict[str, Any]]) -> str:
    labels = [str(a.get("label")) for a in audiences if a.get("label")]
    if not labels:
        return "Proactive test of the highest-quality untested audiences for this account."
    joined = ", ".join(labels)
    return (
        f"Daily proactive suggestion: test the top {len(labels)} untested audience(s) next "
        f"({joined}). Config mirrors the account's winning campaign; everything stays "
        "PAUSED until you approve."
    )


def _recent_labels(playbooks: list[dict[str, Any]] | None) -> list[str]:
    """Interest labels already tested by the provided recent playbooks (to exclude).

    Collects only from the playbooks passed in (the caller decides what "recent"
    means and how many), so this never reads the global store implicitly. Defensive
    against partial/missing playbook shapes.
    """
    labels: list[str] = []
    for book in (playbooks or [])[:5]:
        for segment in (book or {}).get("segments", []) or []:
            for interest in segment.get("interests", []) or []:
                if interest:
                    labels.append(str(interest))
    return list(dict.fromkeys(labels))


# ---------------------------------------------------------------------------
# Scheduled run (24h debounce, mirrors monitoring_scheduler)
# ---------------------------------------------------------------------------


async def run_scheduled_opportunities(
    load_knowledge: KnowledgeLoader,
    *,
    load_playbooks: PlaybookLoader | None = None,
    account_id: str | None = None,
    per_segment_budget_usd: float | None = None,
    storage_dir: Path = STORAGE_DIR,
    send_alert: AlertSender | None = None,
    enrich_creatives: bool | None = None,
    interval_hours: int = 24,
    force: bool = False,
    today: date | datetime | None = None,
) -> dict[str, Any]:
    """Daily debounced proactive run. SUGGEST-ONLY — never executes a Meta change.

    When due (no completed run inside ``interval_hours``): generate packets,
    persist each as an approval (dedup by deterministic id), notify via
    ``send_alert``, and log the run. When a Claude key is configured (or
    ``enrich_creatives=True``) the packet's per-segment new-angle briefs are
    enriched via the LLM, with a deterministic fallback otherwise.
    """
    now = datetime.now(timezone.utc)
    day = _as_date(today)
    previous_runs = list_opportunity_runs(storage_dir=storage_dir)
    last_completed = _first_completed_run(previous_runs)

    if not force and last_completed and _within_interval(last_completed, now, interval_hours):
        run = {
            "id": _run_id(now),
            "status": "skipped",
            "mode": "suggest_only",
            "startedAt": now.isoformat(),
            "finishedAt": now.isoformat(),
            "reason": f"Opportunities already generated within the last {interval_hours} hours.",
            "approvalsCreated": 0,
            "executionAllowed": False,
        }
        save_opportunity_run(run, storage_dir=storage_dir)
        return {"ok": True, "skipped": True, "mode": "suggest_only", "run": run, "approvals": []}

    run: dict[str, Any] = {
        "id": _run_id(now),
        "status": "running",
        "mode": "suggest_only",
        "startedAt": now.isoformat(),
        "intervalHours": interval_hours,
    }
    try:
        knowledge = load_knowledge() if load_knowledge else None
        playbooks = load_playbooks() if load_playbooks else None
        packets = generate_opportunity_packets(
            knowledge,
            playbooks,
            account_id=account_id,
            per_segment_budget_usd=per_segment_budget_usd,
            today=day,
        )

        if _should_enrich(enrich_creatives):
            for packet in packets:
                await _enrich_packet_creatives(packet, knowledge)

        saved: list[dict[str, Any]] = []
        notifications: list[dict[str, Any]] = []
        for packet in packets:
            stored = _persist_approval(packet, storage_dir=storage_dir)
            saved.append(stored)
            if send_alert is not None:
                try:
                    notifications.append(send_alert(stored))
                except Exception:  # noqa: BLE001 - notify is best-effort, never fatal
                    notifications.append({"ok": False, "skipped": True})

        finished = datetime.now(timezone.utc)
        run.update(
            {
                "status": "completed",
                "finishedAt": finished.isoformat(),
                "approvalsCreated": len(saved),
                "approvalIds": [item.get("id") for item in saved],
                "notificationsSent": len(notifications),
                "executionAllowed": False,
            }
        )
        save_opportunity_run(run, storage_dir=storage_dir)
        return {
            "ok": True,
            "skipped": False,
            "mode": "suggest_only",
            "run": run,
            "approvals": saved,
            "notifications": notifications,
        }
    except Exception as exc:  # noqa: BLE001 - log a failed run, never crash the loop
        finished = datetime.now(timezone.utc)
        run.update(
            {
                "status": "failed",
                "finishedAt": finished.isoformat(),
                "error": str(exc),
                "executionAllowed": False,
            }
        )
        save_opportunity_run(run, storage_dir=storage_dir)
        return {"ok": False, "skipped": False, "mode": "suggest_only", "run": run, "error": str(exc)}


async def _enrich_packet_creatives(packet: dict[str, Any], knowledge: dict[str, Any] | None) -> None:
    """Replace each per-segment ``newAngleBriefs`` with LLM-enriched briefs.

    Deterministic fallback is built into ``generate_creative_angle_briefs``, so a
    missing key / error never changes the contract shape.
    """
    analysis = (knowledge or {}).get("analysis", {}) or {}
    creatives = packet.get("opportunity", {}).get("creatives") or []
    for block in creatives:
        if not isinstance(block, dict):
            continue
        briefs = await generate_creative_angle_briefs(analysis, [block.get("segment")])
        if briefs:
            block["newAngleBriefs"] = briefs


def _persist_approval(packet: dict[str, Any], *, storage_dir: Path) -> dict[str, Any]:
    if create_approval_request is None:  # pragma: no cover - defensive
        return packet
    return create_approval_request(packet, storage_dir=storage_dir)


# ---------------------------------------------------------------------------
# Run log helpers (mirror monitoring_scheduler)
# ---------------------------------------------------------------------------


def list_opportunity_runs(*, storage_dir: Path = STORAGE_DIR) -> list[dict[str, Any]]:
    payload = read_json(storage_dir / RUNS_FILENAME, [])
    return payload if isinstance(payload, list) else []


def save_opportunity_run(run: dict[str, Any], *, storage_dir: Path = STORAGE_DIR) -> None:
    rows = [run, *list_opportunity_runs(storage_dir=storage_dir)]
    write_json_atomic(storage_dir / RUNS_FILENAME, rows[:100])


def _first_completed_run(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((run for run in runs if run.get("status") == "completed"), None)


def _within_interval(run: dict[str, Any], now: datetime, interval_hours: int) -> bool:
    finished = _parse_datetime(str(run.get("finishedAt") or run.get("startedAt") or ""))
    return finished is not None and now - finished < timedelta(hours=interval_hours)


def _parse_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _run_id(now: datetime) -> str:
    return f"opportunity_run_{now.strftime('%Y%m%dT%H%M%SZ')}"


def opportunity_approval_id(day: date | datetime | None = None) -> str:
    """Deterministic per-day approval id: running twice the same day REPLACES the
    suggestion (no duplicate); a new day yields a new one."""
    return f"proactive_audience_test_{_as_date(day).strftime('%Y%m%d')}"


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _as_date(value: date | datetime | None) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.now(timezone.utc).date()


def _should_enrich(flag: bool | None) -> bool:
    if flag is not None:
        return flag
    import os

    return bool(
        os.getenv("ANTHROPIC_API_KEY", "").strip()
        or os.getenv("OPENAI_API_KEY", "").strip()
    )


def _slug(value: str) -> str:
    text = "".join(char if char.isalnum() else "_" for char in str(value).lower())
    while "__" in text:
        text = text.replace("__", "_")
    return text.strip("_")
