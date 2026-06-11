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

Light theme, three zones, no vertical scrolling at desktop widths (≥1180px). On narrower
viewports the zones stack: KPIs → chart/funnel → Agent Office.

### 3.1 Left — KPI rail (~200px)

Five KPIs, stacked, each: small uppercase label, large value, one-line plain-language delta.

| KPI | Value | Delta line | Source |
|---|---|---|---|
| Spend · 7d | currency | pace vs budget ("on pace", "ahead of budget") | existing filtered metrics (`spendUsd`) |
| Leads | count | Δ% vs previous 7 days | existing metrics (`leads`) |
| Cost / Lead | currency | Δ% vs previous 7 days, worded ("▼ 12% — improving") | spend ÷ leads |
| Telegram STARTs | count | Δ% vs previous 7 days | existing metrics (`telegramSubscribers`) |
| CTR | percent | Δ in points, worded ("▼ 0.3pt — watch") | clicks ÷ impressions |

Tone colors (green/red) apply only to the delta line, never the value. Purchases/ROAS are
deliberately excluded until purchase tracking is activated (see `meta-ad-agent-signals-state`
memory); the rail design leaves room to add a sixth KPI later.

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
   and elapsed time (e.g. "working — scanning 14 ad sets · 2m"; "idle — next run 14:00").

A small header line summarizes: "2 working · 2 idle". ("Moving" is not a backend state — the
walk animation plays as a transition whenever an agent's state changes between polls.)

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
      "nextRunAt": null              // ISO timestamp when state == "scheduled"
    }
  ],
  "updatedAt": "2026-06-11T10:41:00Z"
}
```

Backend implementation: a small in-process **agent activity registry** (module-level, like the
existing TTL caches) that schedulers/jobs mark on start/finish (`begin(agent_id, activity)` /
`end(agent_id)`), plus next-run times read from the existing scheduler config. No new storage
files; state is ephemeral and resets on restart (acceptable — it reflects "right now").

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

- **Frontend (vitest, jsdom):** KPI rail renders values/deltas/tones from fixture metrics;
  funnel renders five stages with widths; Agent Office renders working/idle/scheduled states
  and the summary line; reduced-motion fallback renders without animated classes. House
  style: `// @vitest-environment jsdom`, assert with `.toBeTruthy()`.
- **Backend (pytest):** activity registry begin/end transitions; `/api/agents/status` shape,
  session guard (401 unauthenticated), viewer access allowed; scheduler integration marks
  Monitor working during a scan.
- **Regression:** full suites stay green (baseline 522 backend + 51 frontend, minus tests that
  covered deleted web-only UI, which are removed with their components).
- `npm run lint` and `npm run build` pass.

## 8. Out of scope

- Purchases/ROAS KPIs (blocked on operator-side purchase tracking activation)
- Any Telegram or MCP connector changes
- Rankings/Settings/Team redesigns
- Dark-theme polish beyond what falls out of existing tokens
- Deployment (separate step; production restart requires explicit operator authorization)
