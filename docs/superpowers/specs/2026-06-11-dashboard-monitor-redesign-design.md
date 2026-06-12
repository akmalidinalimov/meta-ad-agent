# Dashboard Monitor Redesign — "Lean Monitor" (E+D Hybrid, Light)

**Date:** 2026-06-11
**Status:** Approved by operator (visual mockups reviewed in brainstorming session; light theme selected)
**Branch target:** `feat/rbac-roles` (or a new branch off it)

## 1. Goal

The web dashboard's only job is **monitoring**. Control and approvals happen in Telegram and the
Claude.ai connector. The current Monitor view is cluttered (decision hero, 8-item problem queue,
approval cards, insights panel, stacked charts); the redesign replaces it with a single-screen,
zero-scroll view: KPIs left, one chart + funnel center, an animated "Agent Office" right.

Chosen direction: **Single-Screen Focus layout (E) + Agent Office (D), light theme** — selected
from five full-size mockups (Mission Control, Calm Brief, Bento Grid, Live Pulse, Single-Screen).
Mockups archived in `.superpowers/brainstorm/21-1781188070/content/` (gitignored; reference only).

## 2. Information architecture

| Tab | Fate | Notes |
|---|---|---|
| **Monitor** | Redesigned — becomes the home screen | The new single-screen view |
| **Chat** | **Removed from web** | Conversation moves to Telegram / Claude.ai connector |
| Approval cards | **Removed from web** | Approvals live in Telegram (inline buttons) |
| **Rankings** | Kept as-is, secondary tab | |
| **Settings** | Kept as-is, secondary tab | |
| **Team** | Kept as-is, secondary tab | RBAC management stays on the web |

RBAC is unchanged: viewers see Monitor/Rankings/Settings read-only; admin/owner also see Team.
Login flow, session auth, and the topbar (title, data-source pill, refresh) are unchanged.

## 3. Monitor screen layout

Light theme, three zones, no vertical scrolling at desktop widths (≥1180px). Mobile gets its
own layout (§3.4), not just stacked desktop zones.

### 3.1 Left — KPI rail (~200px)

Five KPIs, stacked, each: small uppercase label, large value, one-line plain-language delta.

| KPI | Value | Delta line | Source |
|---|---|---|---|
| Spend · 7d | currency | pace vs weekly budget target if configured, else Δ% vs previous 7 days | existing filtered metrics (`spendUsd`) |
| Leads | count | Δ% vs previous 7 days | existing metrics (`leads`) |
| Cost / Lead | currency | Δ% vs previous 7 days, worded ("▼ 12% — improving") | spend ÷ leads |
| Telegram STARTs | count | Δ% vs previous 7 days | existing metrics (`telegramSubscribers`) |
| CTR | percent | Δ in points, worded ("▼ 0.3pt — watch") | clicks ÷ impressions |

Tone colors (green/red) apply only to the delta line, never the value. Purchases/ROAS are
deliberately excluded until purchase tracking is activated (see `meta-ad-agent-signals-state`
memory); the rail design leaves room to add a sixth KPI later.

**Delta integrity rules:**
- "Spend pace vs budget" only renders when a weekly budget target exists — a new optional
  field on the Settings tab (stored alongside existing dashboard settings). Without it, the
  delta falls back to a plain Δ% comparison; the UI never invents a pace claim.
- All Δ comparisons use **complete days only**: the current window is the last 7 complete
  days vs the 7 before that. Today's partial data is shown in the trend chart but excluded
  from delta math, so the rail doesn't show false drops every morning.
- The topbar shows one **freshness stamp** for the whole screen ("data as of 10:41"), driven
  by the live-fetch timestamp; if the last fetch fell back to snapshot data, the stamp says so
  ("snapshot · 09:58"). The agent panel inherits this rather than having its own.

### 3.2 Center — trend + funnel

- **Trend:** one recharts LineChart, 14 days, two series (Spend, Leads), legend above,
  existing `chartConfig.ts` formatters. No other charts.
- **Funnel:** horizontal bars — Impressions → Clicks (with CTR in the label) → Leads →
  Telegram STARTs → Webinar attended — each with absolute count at the right. Reuses the
  existing `deriveFunnel` logic from `src/lib/analytics.ts`.

### 3.3 Right — Agent Office (~320px)

Two parts:

1. **Office scene** (~200px tall): a stylized floor with a center table and one desk per agent.
   Avatars glow (pulsing ring) while working, show a green/gray status dot, walk between desk
   and table when their state changes, and dim when idle. Reuses/adapts the existing agent-office
   CSS in `App.css` (desk, walk, pulse keyframes already present). All animation respects
   `prefers-reduced-motion: reduce` (static fallback with status dots only).
2. **Status list** below the scene: one row per agent — avatar, name, live status sentence,
   and elapsed time (e.g. "working — scanning 14 ad sets · 2m"). Idle agents show their last
   real activity instead of a bare "idle" (e.g. "last: finished scan, 2h ago · next 14:00") so
   the panel never reads as dead between scheduled runs.
3. **Recent activity feed** (compact, last 5 events) under the status list: timestamped lines
   of completed agent work, e.g. "10:41 Monitor — scan done, 14 ad sets healthy, 1 flagged",
   "09:58 Analyst — KPI digest sent to Telegram". The office is a living log of work done,
   not just a right-now snapshot — this is what keeps the screen honest *and* alive when all
   jobs are between runs.

A small header line summarizes: "2 working · 2 idle". ("Moving" is not a backend state — the
walk animation plays as a transition whenever an agent's state changes between polls.)

### 3.4 Mobile / Telegram Mini App layout (≤768px)

The operator will most often glance at this from a phone, frequently inside Telegram (the
dashboard is already reachable via web_app buttons). Mobile is a first-class layout, not
stacked desktop zones:

1. **KPI grid first**: the five KPIs as a 2-column grid (Spend spanning full width on top, or
   2×3 with one empty cell), values slightly smaller, deltas intact. This alone answers "is
   everything fine?" without scrolling.
2. **Agent strip second**: the office scene is replaced by a horizontal status strip — avatar
   + status dot per agent in one row, with the "2 working · 2 idle" summary; tapping/expanding
   reveals the status list + recent activity feed. No walking animation on mobile.
3. **Trend + funnel last**, inside a collapsed-by-default section ("Trend & funnel ▾") to keep
   the initial viewport to roughly one screen.

Target: KPIs + agent strip visible without scrolling on a ~380px-wide viewport.

## 4. Agent Office — data contract (real data, not theater)

Four named agents map to real backend activity. An agent never shows "working" unless a real
job is running.

| Agent | Backed by | Working when | Idle label |
|---|---|---|---|
| **Monitor** | 4-hourly monitoring scheduler | a monitoring scan is executing | "next scan HH:MM" |
| **Analyst** | analysis/insight runs + agentic chat tool loops | an analysis or tool-use loop is in flight | "idle" |
| **Planner** | daily opportunity finder | the daily opportunity job is executing | "next run HH:MM" |
| **Creative** | creative ranking/refresh jobs | a creative ranking fetch/refresh is running | "idle" |

### 4.1 New endpoint

`GET /api/agents/status` (session-guarded, all roles incl. viewer):

```json
{
  "agents": [
    {
      "id": "monitor",
      "name": "Monitor",
      "state": "working",            // "working" | "idle" | "scheduled"
      "activity": "scanning 14 ad sets",
      "sinceSeconds": 120,           // elapsed in current state, null if unknown
      "nextRunAt": null,             // ISO timestamp when state == "scheduled"
      "lastActivity": "finished scan — 14 ad sets healthy",
      "lastActiveAt": "2026-06-11T08:41:00Z"
    }
  ],
  "events": [                        // newest first, capped at 20
    { "agentId": "monitor", "summary": "scan done — 14 ad sets healthy, 1 flagged",
      "at": "2026-06-11T10:41:00Z" }
  ],
  "updatedAt": "2026-06-11T10:41:00Z"
}
```

Backend implementation: a small **agent activity registry** that schedulers/jobs mark on
start/finish (`begin(agent_id, activity)` / `end(agent_id, summary)`), plus next-run times read
from the existing scheduler config. Live working state is in-process/ephemeral, but completed
events and `lastActiveAt` are persisted to `backend/storage/agent_activity.json` (same pattern
as the other JSON stores, capped at ~50 events) so a service restart doesn't wipe the feed and
make the office look like nothing ever happened.

Frontend polls every 30s (aligned with the existing refresh cadence); on fetch failure the
office shows the last known state with a stale indicator rather than erroring.

## 5. Removals

Deleted from the web bundle (code + CSS + tests updated accordingly):

- Chat view (`CampaignChatView`), agent chat panel, campaign-chat intro, starter prompts
- ApprovalQueue and all approval card UI
- DecisionHero, TopProblemsPanel (operator priority queue), InsightsPanel
- The collapsed details panels (CreativeTablePanel, PlacementPanel, AudiencePanel) are
  deleted — their data already exists as Rankings tables
- Related dead code in `Dashboard.tsx`, `operatorAttention.ts` (if no longer referenced),
  and the corresponding CSS blocks in `App.css`

Backend chat/approval **APIs stay** — Telegram and the MCP connector use them. Only the web UI
surface is removed.

## 6. Visual language

- Light theme as primary (existing auto dark-mode media query may remain for the new
  components, but light is the design target).
- Existing design tokens in `index.css` (teal accent `#0f766e`, radius 8, current type scale)
  are kept — this is a layout/declutter redesign, not a rebrand.
- Recharts stays for the trend chart; funnel bars are plain divs (as today); the office scene
  is DOM + CSS animation (no canvas/WebGL).

## 7. Testing

- **Frontend (vitest, jsdom):** KPI rail renders values/deltas/tones from fixture metrics
  (incl. complete-days delta windows and the no-budget-target fallback); funnel renders five
  stages with widths; Agent Office renders working/idle/scheduled states, last-activity lines,
  the recent-events feed, and the summary line; mobile agent strip renders; reduced-motion
  fallback renders without animated classes. House style: `// @vitest-environment jsdom`,
  assert with `.toBeTruthy()`.
- **Backend (pytest):** activity registry begin/end transitions and event persistence
  (capped, survives reload from JSON); `/api/agents/status` shape incl. events, session guard
  (401 unauthenticated), viewer access allowed; scheduler integration marks Monitor working
  during a scan; weekly budget target setting round-trips through the settings API.
- **Regression:** full suites stay green (baseline 522 backend + 51 frontend, minus tests that
  covered deleted web-only UI, which are removed with their components).
- `npm run lint` and `npm run build` pass.

## 8. Out of scope

- Purchases/ROAS KPIs (blocked on operator-side purchase tracking activation)
- Any Telegram or MCP connector changes
- Rankings/Settings/Team redesigns
- Dark-theme polish beyond what falls out of existing tokens
- Deployment (separate step; production restart requires explicit operator authorization)
