"""Agentic free-text brain for the Telegram bot.

This replaces the templated free-text router with a real Anthropic tool-use loop:
the model reasons like a senior media buyer, fetches live Meta data ONLY when the
answer needs it, and takes actions through write tools.

Action policy (enforced in ``_run_tool``, not just prompted):

* Reads (``list_campaigns``/``get_campaign``/``get_adset_creatives``/``insights``/
  ``search``/``account_summary``) reuse the ``mcp_server`` async helpers directly.
* Reversible / off / small writes apply IMMEDIATELY:
  - ``set_status`` to PAUSED or ARCHIVED.
  - ``set_budget`` to a value within ±25% of current (including any decrease).
* Spend-increasing / notable writes are NOT executed — they store a pending
  pointer (kind=``agentic``) and return ``{needsApproval, proposal}`` so the
  operator can reply "approve" (text) or tap an inline Approve button:
  - ``set_status`` to ACTIVE (starts spending).
  - ``set_budget`` increase beyond +25%.
  - ``create_test_campaign`` (creates a brand-new PAUSED test campaign).

``live_writes_enabled()`` is honored on every write path — disabled => error,
no Meta call.

The model call is factored behind ``_create_message`` so tests can monkeypatch
the SDK call without a network round-trip.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from . import config
from .mcp_server import (
    _account_summary,
    _cents_to_usd,
    _get_adset_creatives,
    _get_campaign,
    _get_insights,
    _list_campaigns,
    _search,
)

logger = logging.getLogger(__name__)

_BUDGET_DELTA_FRACTION = 0.25
_MAX_TOOL_ITERATIONS = 8
_MAX_REPLY_CHARS = 3500


SYSTEM_PROMPT = """You are the Meta Ads operator for the Shahlo AI-course business (market: Uzbekistan), texting with the owner over Telegram. Act like a sharp, senior media buyer — not a report generator.

GOLDEN RULE — answer the actual question at the right altitude.
- Answer what was asked, nothing more. A one-line question gets a one-line answer. Never volunteer a full account overview or campaign dump unless asked.
- No templates, no preamble, no "let me pull a snapshot…". Just answer.

WHEN TO USE TOOLS — only when the answer depends on live account data.
- Use NO tools for: greetings; "what can you do / how can you help"; definitions and how-to ("what's a good CTR?", "CBO vs ABO"); general strategy that isn't about a specific current entity. Answer those directly from this prompt.
- Use the tools when the question references the account's real state, names/lists campaigns, asks for current numbers, or asks you to change something. Fetch exactly what you need (scope to the entity / breakdown) — don't pull everything.
- Never invent campaign names, IDs, or numbers. Fetch them if you need them.

REASON LIKE A TOP-0.1% PERFORMANCE MARKETER.
Results come from a stack of layers: objective → budget/bid → audience → placement → creative → funnel/landing. When asked "why" or "what should I do", diagnose by isolating the responsible layer and explain the causal chain in 1-3 sentences (e.g. "CTR is fine but lead rate collapsed → it's the landing page, not the creative"). Lead with cost-per-result and result volume; CTR and CPM are secondary. Judge against THIS account's UZ norms, not Western benchmarks: CPM ~$0.5-1.5, CTR ~1.5-3%, CPL ~$0.07-0.10.

ACTION POLICY — to change the account, call the write tools; don't just describe.
- set_status to PAUSED or ARCHIVED, and budget changes within ±25% (including any decrease) happen IMMEDIATELY — confirm what changed.
- Activating (status ACTIVE), budget INCREASES beyond +25%, and creating a new campaign require operator approval: the tool returns needsApproval with a proposal. Relay that proposal plainly and tell the operator to reply "approve" to proceed (do not claim it's done).

STYLE — plain language, lead with the answer, then the 2-4 numbers that matter. Concise, Telegram-friendly. A little HTML (<b>, <i>) and the occasional emoji is fine; don't over-format. Keep replies under ~3500 characters."""


# --- Anthropic tool schemas ---------------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "list_campaigns",
        "description": "List campaigns (live). Optional status filter: ACTIVE | PAUSED | ARCHIVED.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "ACTIVE | PAUSED | ARCHIVED"},
            },
        },
    },
    {
        "name": "get_campaign",
        "description": "Full live config of one campaign: ad sets, targeting (age/geo/interests/custom audiences/placements), optimization/billing/bid, A/B-test status. Accepts a name fragment or id.",
        "input_schema": {
            "type": "object",
            "properties": {"name_or_id": {"type": "string"}},
            "required": ["name_or_id"],
        },
    },
    {
        "name": "get_adset_creatives",
        "description": "Creatives for an ad set, ranked by lifetime performance, with stats, thumbnails and video links.",
        "input_schema": {
            "type": "object",
            "properties": {"adset_id": {"type": "string"}},
            "required": ["adset_id"],
        },
    },
    {
        "name": "insights",
        "description": "Live performance AGGREGATED over the date window. level: campaign|adset|ad. Pass object_id to scope to one entity. breakdowns: any of age, gender, country, region, publisher_platform, platform_position. date_preset e.g. last_7d, last_30d, maximum.",
        "input_schema": {
            "type": "object",
            "properties": {
                "level": {"type": "string", "description": "campaign | adset | ad"},
                "object_id": {"type": "string"},
                "breakdowns": {"type": "array", "items": {"type": "string"}},
                "date_preset": {"type": "string"},
            },
            "required": ["level"],
        },
    },
    {
        "name": "search",
        "description": "Find campaigns and ad sets by name fragment.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "account_summary",
        "description": "Ad account name, currency, and status.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "set_status",
        "description": "Set a campaign or ad set status. level: campaign|adset. status: ACTIVE|PAUSED|ARCHIVED. PAUSED/ARCHIVED apply immediately; ACTIVE (starts spending) returns needsApproval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "level": {"type": "string", "description": "campaign | adset"},
                "id": {"type": "string"},
                "status": {"type": "string", "description": "ACTIVE | PAUSED | ARCHIVED"},
            },
            "required": ["level", "id", "status"],
        },
    },
    {
        "name": "set_budget",
        "description": "Set an ad set's daily budget in USD. Changes within ±25% (incl. decreases) apply immediately; an increase beyond +25% returns needsApproval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "adset_id": {"type": "string"},
                "daily_budget_usd": {"type": "number"},
            },
            "required": ["adset_id", "daily_budget_usd"],
        },
    },
    {
        "name": "create_test_campaign",
        "description": "Build a brand-new PAUSED test campaign for the top untested audiences. Always returns needsApproval — nothing is created until the operator approves.",
        "input_schema": {
            "type": "object",
            "properties": {"note": {"type": "string"}},
        },
    },
]


# --- Tool dispatch ------------------------------------------------------------


async def _find_entity(level: str, entity_id: str) -> dict[str, Any]:
    """Look up an entity's current live record (status + budget) for policy decisions."""
    from .knowledge_base import load_knowledge_base
    from .meta_live import get_live_account

    acct = await get_live_account(knowledge=load_knowledge_base() or {})
    pool = acct.campaigns if level == "campaign" else acct.adsets
    return next((e for e in pool if str(e.get("id")) == str(entity_id)), {}) or {}


async def _run_tool(name: str, args: dict[str, Any], *, operator_key: str) -> Any:
    """Execute one tool call. Reads hit the mcp_server helpers; writes enforce the
    action policy (immediate vs. needs-approval) and stash a pending pointer when
    operator approval is required."""
    if name == "list_campaigns":
        return await _list_campaigns(args.get("status"))
    if name == "get_campaign":
        return await _get_campaign(args.get("name_or_id", ""))
    if name == "get_adset_creatives":
        return await _get_adset_creatives(args.get("adset_id", ""))
    if name == "insights":
        return await _get_insights(
            args.get("level", "campaign"),
            args.get("object_id"),
            args.get("breakdowns"),
            args.get("date_preset", "maximum"),
        )
    if name == "search":
        return await _search(args.get("query", ""))
    if name == "account_summary":
        return await _account_summary()
    if name == "set_status":
        return await _set_status(
            str(args.get("level", "")), str(args.get("id", "")), str(args.get("status", "")),
            operator_key=operator_key,
        )
    if name == "set_budget":
        return await _set_budget(
            str(args.get("adset_id", "")), float(args.get("daily_budget_usd", 0)),
            operator_key=operator_key,
        )
    if name == "create_test_campaign":
        return _create_test_campaign(operator_key=operator_key)
    return {"ok": False, "error": f"Unknown tool: {name}"}


async def _set_status(level: str, entity_id: str, status: str, *, operator_key: str) -> dict[str, Any]:
    from .config import live_writes_enabled
    from .meta_client import MetaApiError, get_meta_config, update_ad_set, update_campaign
    from .pending_context_store import set_pending

    status = status.upper()
    if status not in {"ACTIVE", "PAUSED", "ARCHIVED"}:
        return {"ok": False, "error": "status must be ACTIVE, PAUSED, or ARCHIVED."}
    if not live_writes_enabled():
        return {"ok": False, "error": "live writes disabled"}

    entity = await _find_entity(level, entity_id)
    name = entity.get("name") or entity_id

    if status == "ACTIVE":
        # Spend-starting -> propose, don't execute.
        set_pending(
            operator_key,
            {"kind": "agentic", "action": "set_status", "level": level, "id": entity_id,
             "status": "ACTIVE", "label": name},
        )
        return {
            "needsApproval": True,
            "proposal": f"Activate {name}? This will start spending. Reply approve to go live.",
        }

    config_ = get_meta_config()
    writer = update_campaign if level == "campaign" else update_ad_set
    try:
        await writer(config_, str(entity_id), {"status": status})
    except MetaApiError as error:
        return {"ok": False, "error": str(error)}
    return {"ok": True, "level": level, "id": entity_id, "status": status, "name": name}


async def _set_budget(adset_id: str, daily_budget_usd: float, *, operator_key: str) -> dict[str, Any]:
    from .config import live_writes_enabled
    from .meta_client import MetaApiError, get_meta_config, update_ad_set
    from .pending_context_store import set_pending

    if not live_writes_enabled():
        return {"ok": False, "error": "live writes disabled"}

    entity = await _find_entity("adset", adset_id)
    name = entity.get("name") or adset_id
    current = _cents_to_usd(entity.get("daily_budget")) or 0.0
    new = float(daily_budget_usd)

    # Increase beyond +25% -> propose. Anything else (decrease, or within +25%) applies.
    if current > 0 and new > current * (1 + _BUDGET_DELTA_FRACTION):
        set_pending(
            operator_key,
            {"kind": "agentic", "action": "set_budget", "id": adset_id, "new_usd": new, "label": name},
        )
        return {
            "needsApproval": True,
            "proposal": (
                f"Raise {name} daily budget from ${current:.2f} to ${new:.2f} "
                f"(+{((new / current) - 1) * 100:.0f}%)? Reply approve to apply."
            ),
        }

    config_ = get_meta_config()
    try:
        await update_ad_set(config_, str(adset_id), {"daily_budget": int(round(new * 100))})
    except (MetaApiError, ValueError) as error:
        return {"ok": False, "error": str(error)}
    return {"ok": True, "id": adset_id, "daily_budget_usd": new, "name": name}


def _create_test_campaign(*, operator_key: str) -> dict[str, Any]:
    from .approval_store import create_approval_request
    from .knowledge_base import load_knowledge_base
    from .meta_client import get_meta_config
    from .opportunity_finder import build_autonomous_campaign
    from .pending_context_store import set_pending
    from .playbook_store import load_playbooks

    config_ = get_meta_config()
    approval = build_autonomous_campaign(
        load_knowledge_base(),
        load_playbooks(),
        account_id=(config_.ad_account_id or None),
        n_audiences=3,
        n_creatives=5,
        pixel_id=(config_.pixel_id or None),
    )
    if approval is None:
        return {"ok": False, "error": "no usable audience data"}

    saved = create_approval_request(approval)
    after = saved.get("after") or {}
    name = after.get("name") or approval.get("title") or "Test campaign"
    adsets = after.get("adsets") or []
    audiences = [str(a.get("name", "")).replace(" - DRAFT", "") for a in adsets if a.get("name")]
    total_budget = sum((float(a.get("daily_budget") or 0) / 100) for a in adsets)

    set_pending(
        operator_key,
        {"kind": "agentic", "action": "create", "approvalId": saved["id"], "label": name},
    )
    aud_line = f"audiences: {', '.join(audiences)}" if audiences else "top untested audiences"
    budget_line = f"${total_budget:,.0f}/day total" if total_budget else "default budget"
    return {
        "needsApproval": True,
        "proposal": (
            f"Plan a PAUSED test campaign — {aud_line}; {budget_line}. "
            "PAUSED test; reply approve to create."
        ),
    }


# --- Model call seam ----------------------------------------------------------


async def _create_message(client: Any, **kwargs: Any) -> Any:
    """Single seam over the Anthropic Messages call so tests can monkeypatch the
    model round-trip without a network call."""
    return await client.messages.create(**kwargs)


def _build_client() -> Any:
    """Construct the AsyncAnthropic client exactly as llm_provider does."""
    import httpx
    from anthropic import AsyncAnthropic

    from .meta_client import get_ssl_context

    return AsyncAnthropic(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        http_client=httpx.AsyncClient(verify=get_ssl_context()),
    )


def _system_blocks() -> list[dict[str, Any]]:
    return [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]


def _content_blocks_to_list(content: Any) -> list[Any]:
    """Normalize the SDK's assistant content (list of typed blocks) into the dict
    shape the messages list expects on the next turn."""
    blocks: list[Any] = []
    for block in content:
        btype = getattr(block, "type", None)
        if btype == "text":
            blocks.append({"type": "text", "text": block.text})
        elif btype == "tool_use":
            blocks.append({"type": "tool_use", "id": block.id, "name": block.name, "input": block.input})
    return blocks


async def agentic_reply(message: str, *, operator_key: str) -> str:
    """Run the Anthropic tool-use loop for one free-text operator message and return
    the model's final text. Degrades to a friendly string on any error."""
    from .agent_activity import begin as agent_begin, end as agent_end

    model = config.anthropic_model()
    try:
        client = _build_client()
    except Exception:  # noqa: BLE001 - SDK/import/config failure -> degrade
        logger.exception("agentic_chat: failed to build Anthropic client")
        return "I hit an error reaching the model. Try again in a moment, or tap /menu."

    # Single-slot per agent: concurrent operator messages share the "analyst"
    # slot (last begin wins) — acceptable for a dashboard status display.
    agent_begin("analyst", "answering an operator question")
    done_summary: str | None = None
    try:
        messages: list[dict[str, Any]] = [{"role": "user", "content": message}]
        final_text = ""
        for _ in range(_MAX_TOOL_ITERATIONS):
            response = await _create_message(
                client,
                model=model,
                max_tokens=4096,
                system=_system_blocks(),
                tools=TOOL_SCHEMAS,
                messages=messages,
            )

            text_parts = [b.text for b in response.content if getattr(b, "type", None) == "text"]
            final_text = "".join(text_parts).strip()

            if getattr(response, "stop_reason", None) != "tool_use":
                break

            messages.append({"role": "assistant", "content": _content_blocks_to_list(response.content)})

            tool_results: list[dict[str, Any]] = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                try:
                    result = await _run_tool(block.name, dict(block.input or {}), operator_key=operator_key)
                except Exception as error:  # noqa: BLE001 - surface to the model, don't crash the loop
                    logger.exception("agentic_chat: tool %s failed", block.name)
                    result = {"ok": False, "error": str(error)}
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, default=str),
                    }
                )
            messages.append({"role": "user", "content": tool_results})
        done_summary = "answered an operator question"
        return final_text or "Done."
    except Exception:  # noqa: BLE001 - any loop/API failure -> degrade
        logger.exception("agentic_chat: tool loop failed")
        return "I hit an error working on that. Try again, or tap /menu."
    finally:
        agent_end("analyst", done_summary)
        try:
            await client.close()
        except Exception:  # noqa: BLE001 - best-effort close
            pass


# --- Pending-approval execution ----------------------------------------------


def execute_pending(pending: dict[str, Any], operator_key: str) -> str:
    """Execute an approved pending agentic action and return a confirmation string."""
    from .config import live_writes_enabled

    action = pending.get("action")
    label = pending.get("label") or "the change"

    if not live_writes_enabled() and action in {"set_status", "set_budget"}:
        return "Live writes are disabled, so I couldn't apply that."

    if action == "set_status":
        from .meta_client import MetaApiError, get_meta_config, update_ad_set, update_campaign

        level = pending.get("level")
        entity_id = str(pending.get("id"))
        status = str(pending.get("status") or "ACTIVE").upper()
        writer = update_campaign if level == "campaign" else update_ad_set
        try:
            import asyncio

            asyncio.run(writer(get_meta_config(), entity_id, {"status": status}))
        except MetaApiError as error:
            return f"❌ Could not apply: {error}"
        if status == "ACTIVE":
            return f"✅ Activated {label} — now live."
        return f"✅ {label} set to {status}."

    if action == "set_budget":
        from .meta_client import MetaApiError, get_meta_config, update_ad_set

        entity_id = str(pending.get("id"))
        new_usd = float(pending.get("new_usd") or 0)
        try:
            import asyncio

            asyncio.run(
                update_ad_set(get_meta_config(), entity_id, {"daily_budget": int(round(new_usd * 100))})
            )
        except (MetaApiError, ValueError) as error:
            return f"❌ Could not apply: {error}"
        return f"✅ {label} budget set to ${new_usd:.2f}/day."

    if action == "create":
        from .execution_service import auto_execute_paused

        approval_id = pending.get("approvalId")
        if not approval_id:
            return "❌ Nothing to create — the draft expired."
        result = auto_execute_paused(approval_id)
        if result.get("ok"):
            return f"✅ Created PAUSED: {label}. Nothing spends until you enable delivery."
        return f"❌ Could not create it: {result.get('blocked') or 'unknown error'}"

    return "Nothing to apply."
