# Flexible Meta Ads connector for a Claude.ai Project — Design

Date: 2026-06-09
Status: Approved (design), pending implementation plan
Branch: feat/review-improvements

## Context

The operator manages the Shahlo AI-course Meta ad account (market: Uzbekistan). We've built a
capable deployed agent (FastAPI on the Oracle VM) with a Telegram bot + web dashboard that can
create, introspect, and bulk-manage campaigns behind an approval gate, plus 24/7 proactive
monitoring. Day-to-day, the operator finds the **Telegram chat cluttered** and the templated,
opinionated flow too rigid for **deep, ad-hoc questions** about audiences, creatives, and
campaigns.

What the operator actually wants: a **clean place to chat** where they can ask anything — shallow
or deep — and get a correct, **live** answer pulled fresh from the Meta API every time, and where
they can **edit** things by asking, without being forced through a fixed template.

Decision (from brainstorming): build a **Claude.ai Project** (Max plan → custom connectors
available) backed by a **flexible connector that exposes granular, always-live Meta tools**. The
Project's Claude composes these tools freely to answer whatever is asked and to make edits. This is
intentionally **more flexible** than routing through our existing opinionated brain — reads are
free-form and live; only destructive edits are gated.

The deployed Telegram/dashboard agent stays as-is for proactive monitoring and alerts. This Project
is a second, cleaner front-end for interactive work.

## Goals

- Ask **any** question about the account and get a correct answer from **fresh** Meta data (no
  stale snapshot, no fixed template).
- Deep slices: performance by **age / gender / country / region / placement / platform**, per
  campaign / ad set / creative.
- **Edit** on request: pause/activate, change budget, archive — reversible edits applied directly,
  destructive edits confirmed first.
- Clean, per-topic conversations (start a new Project chat anytime → never clutters).

## Non-goals

- Replacing the deployed agent's proactive monitoring, Telegram alerts, or its approval/autonomous
  create flows. Those remain.
- Re-using the agent's opinionated routing/templates (roster answer, manage-approval packets). The
  Project deliberately bypasses these for flexibility.
- Hard-deleting campaigns by default ("delete" still means ARCHIVE unless explicitly forced).

## Architecture

```
Claude.ai Project (Max)
  ├─ Custom instructions (flexible persona + edit-safety rules)
  ├─ Project knowledge doc (account context + tool guide + example deep questions)
  └─ Custom connector (remote MCP, OAuth) ──HTTPS──▶ VM /mcp
                                                       │  (mounted in existing FastAPI app, Caddy-fronted)
                                                       ▼
                                              meta_client.*  ──▶  LIVE Meta Marketing API
```

- The connector is a **remote MCP server (Streamable HTTP)** mounted in the existing FastAPI app and
  served at `https://82-70-42-188.sslip.io/mcp` (Caddy already terminates TLS and proxies the app).
- Each tool calls `backend/meta_client.py` functions **live** (no snapshot). A small per-request
  TTL (~10–15s) is allowed only to avoid duplicate identical calls within one reasoning turn;
  default behavior is fresh.
- Tools return compact, structured JSON; the Project's Claude does the reasoning/answering. No
  answer templates on the server side.

## Connector tools

All reads hit the Meta API live. Backed by existing `meta_client` functions
(`get_campaigns`, `get_ad_sets`, `get_ads`, `get_ads_for_adset`, `get_adset_ad_insights`,
`get_insights`, `get_adstudies`, `get_saved_audiences`, `get_video_source`, `update_campaign`,
`update_ad_set`, `get_ad_account_summary`) plus the helpers in `meta_live`/`campaign_specific_analysis`
for name resolution and config formatting.

Reads (instant, fresh):
- `list_campaigns(status?: str, limit?: int)` — id, name, status, effective_status, objective,
  buying_type, daily/lifetime budget, start/stop time.
- `get_campaign(name_or_id: str)` — resolve by id or fuzzy name; return full config: campaign
  fields + ad sets with targeting (age, geo names, interests, **custom-audience names**, placements),
  optimization_goal/billing_event/bid_strategy, is_dynamic_creative, and A/B-test status (adstudies).
- `list_adsets(campaign: str)` — ad sets for a campaign (live).
- `get_adset(adset_id: str)` — full targeting + ranked creatives (lifetime stats) + thumbnails/video links.
- `list_creatives(adset_id: str)` — creatives ranked by performance (results → CTR → impressions)
  with spend/impressions/clicks/CTR/results + thumbnail + watch URL.
- `get_insights(level: campaign|adset|ad, object_id?: str, breakdowns?: [age|gender|country|region|publisher_platform|platform_position], date_preset?: str, since?, until?)`
  — the deep-question engine. Returns rows the Project reasons over.
- `search(query: str)` — find campaigns/ad sets by name fragment.
- `account_summary()` — account name/currency/status (`get_ad_account_summary`).

Writes (confirm only destructive — enforced in the tool):
- `update_status(level: campaign|adset, id: str, status: PAUSED|ACTIVE|ARCHIVED, confirm?: bool=false)`
- `update_budget(adset_id: str, daily_budget_usd: number, confirm?: bool=false)`

Write safety (server-enforced, not just instructions):
- **Reversible** ops (PAUSED/ACTIVE, budget change within ±25% of current) apply immediately and
  return what changed.
- **Destructive** ops — ARCHIVED, pausing a currently-delivering (effective_status==ACTIVE)
  campaign/ad set, or a budget change beyond ±25% — return `{needsConfirmation: true, preview: {...}}`
  unless `confirm=true`. The Project shows the preview, gets the user's "yes", then re-calls with
  `confirm=true`.
- All writes still require `META_LIVE_WRITES_ENABLED=true` on the VM. "delete" maps to ARCHIVE
  (reversible); permanent delete is out of scope for v1.

## Authentication

claude.ai custom (remote MCP) connectors require OAuth. Plan: implement the minimal OAuth the
connector flow expects using the MCP Python SDK's auth support (authorization-code with a single
operator credential), served under the same Caddy host. The operator does a one-time "Allow" when
adding the connector in claude.ai. The `/mcp` route is the only externally reachable surface added;
it must be auth-protected (no anonymous access to account-control tools).

This OAuth handshake is the primary implementation risk/effort; everything else is thin wrappers
over existing code. **Fallback** if the handshake proves impractical: make the existing web
dashboard chat the clean home (same brain, no connector) — tracked as a contingency, not the plan.

## The Project (operator-side artifacts; we generate them)

1. **Custom instructions** — flexible persona, e.g.:
   - "You manage the Shahlo Meta ad account. Answer ANY question by pulling LIVE data with the
     connector tools; go as deep as asked (slice by age/placement/region/etc. via get_insights).
     Never answer from memory — always fetch. For edits: apply reversible changes directly and report
     them; for destructive changes (archive, pausing an active spender, big budget jumps) call the
     tool once to preview, tell me, and only apply after I confirm. Be direct and concise; no fixed
     template."
2. **Knowledge doc** (uploaded to the Project) — account id, business context (Shahlo AI course, UZ,
   Telegram-START funnel, KPI targets), the rule set as *guidance* (archive-not-delete, never touch
   active without naming), a tool reference, and example deep questions. Generated from everything we
   built.
3. **Setup guide** — claude.ai → Settings → Connectors → Add custom connector → paste
   `https://82-70-42-188.sslip.io/mcp` → Allow (OAuth); create Project → paste instructions → upload
   knowledge doc.

## Components / files (anticipated)

- NEW `backend/mcp_server.py` — MCP server (Streamable HTTP) + tool definitions wrapping `meta_client`
  + write-safety logic; OAuth provider config.
- `backend/app.py` — mount the MCP ASGI app at `/mcp`.
- `/etc/caddy/Caddyfile` (VM) — ensure `/mcp` proxies to the app (likely already covered by the
  catch-all reverse_proxy; verify).
- `.env` (VM) — any OAuth secret/keys for the connector.
- NEW deliverable docs: `docs/meta-project/instructions.md`, `docs/meta-project/knowledge.md`,
  `docs/meta-project/setup.md` (the operator-side artifacts).

## Data flow (example: "which age group is cheapest on the income campaign?")

1. Project Claude calls `get_campaign("income")` → resolves the campaign + ad sets (live).
2. Calls `get_insights(level="campaign", object_id=<id>, breakdowns=["age"], date_preset="maximum")`
   → live rows per age band.
3. Reasons over rows, answers with the cheapest age band by cost-per-result. No template; fresh data.

## Testing / verification

- Unit: each tool wrapper returns expected shape from a mocked `meta_client`; write-safety returns
  `needsConfirmation` for destructive ops without `confirm`, applies reversible ops directly.
- Auth: the OAuth discovery + token handshake works against a test client.
- Live (from claude.ai after connect): "what campaigns are active?"; "full config of the income
  campaign"; "performance by placement for the best creative last 30 days"; "pause ad set X" (applies);
  "archive the old test campaigns" (previews → confirm → archives). Confirm every read is live
  (cross-check a value changed in Ads Manager appears immediately).

## Risks

- **OAuth handshake** for claude.ai custom connectors — main effort/uncertainty (mitigation: MCP SDK
  auth; fallback: dashboard chat).
- **Latency vs freshness** — live calls add ~1–2s; acceptable for "fresh". Tiny intra-turn cache
  avoids duplicate calls.
- **Security** — `/mcp` controls a live ad account; must be OAuth-protected, never anonymous. Writes
  still gated by `META_LIVE_WRITES_ENABLED` + destructive-confirm.
- **Meta scopes** — adstudies/custom-audience reads may need `ads_read`/`ads_management`; tools
  degrade gracefully (already permission-safe in `meta_live`).
