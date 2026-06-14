# Guided Campaign Creation (Telegram) — Design Spec

**Date:** 2026-06-13
**Status:** Approved by operator (brainstorm)
**Branch:** `feat/telegram-guided-campaign` (off `feat/rbac-roles`; already carries the RBAC callback fix)

## 1. Goal

When the operator asks the Telegram bot to create a campaign, walk them through an interactive, **guided** choice of **audience** and **creatives** before building the PAUSED test campaign — instead of the current one-shot auto-pick. The autonomous "create one on your own" path stays unchanged for hands-off use.

This also depends on the already-committed RBAC fix (callbacks attributed to the clicker, not the bot), without which the Approve button at the end of the flow denies the operator.

## 2. Decisions (locked, from brainstorm)

- **Creative pool:** the account's **top-performing existing creatives** (the proven winners the autonomous builder already mirrors), shown with thumbnail or watchable video.
- **Selection UX:** **tap-to-toggle** (`➕ Select` ↔ `✅ Selected`) per creative + a final `✅ Use selected (N)` confirm; plus a "use top 5 automatically" shortcut.
- **Audience "specify my own":** **free-text**, parsed by the agentic brain, **echoed back for confirmation** before building.

## 3. Flow

**Routing.** The existing agentic `create_test_campaign` tool is repointed: instead of immediately auto-building, it **starts the guided flow** (returns Step A and stores the pending pointer). The hands-off path is preserved by a distinct trigger — the tool gains an `autonomous: bool` argument the brain sets `true` only for explicit phrasing like "create one on your own / autonomously / without asking," which runs the unchanged immediate `build_autonomous_campaign`. Default (no such phrasing) → guided.

State is carried across button taps in `pending_context_store` under a pointer `{flow:"guided_create", step, audienceChoice, audienceSpec, selectedCreatives, createdAt}` keyed by `tg:<chatId>`.

### Step A — Audience
Bot message "How should I pick the audience?" with inline buttons:
- 🏆 Proven — `gcreate:aud:proven`
- ✨ New — `gcreate:aud:new`
- ✍️ I'll specify — `gcreate:aud:input`

- `proven` → `rank_audiences_for_next_campaign(analysis, prefer_proven=True)` (top tested by quality + Telegram-START signal).
- `new` → existing default (untested, exclude recent labels).
- `input` → bot prompts "Tell me the audience — interests, age, location." The **next free-text message** is parsed by the agent into a targeting spec, which the bot **echoes back** ("Got it: business owners, 25–34, Tashkent — build with this?") with `✅ Yes` / `✍️ Re-enter` before continuing.

Store `audienceChoice` (+ `audienceSpec` for input), advance to Step B.

### Step B — Creatives
- Fetch the account's top-performing creatives (ranked; reuse `_best_existing_creatives` over `analysis.topAds`, enriched to creative media via the live/snapshot creative fetchers).
- Send each (cap ~5–8 for phone responsiveness) as thumbnail/video using the existing `_send_creative_media` rendering pattern (video plays on tap; image → photo; video-fetch failure → thumbnail + "▶️ Watch" link), each with a toggle button `➕ Select` (`gcreate:cre:toggle:<creativeId>`) that flips to `✅ Selected`.
- A trailing control message carries `✅ Use selected (N)` (`gcreate:cre:done`) and `⚡ Use top 5` (`gcreate:cre:auto`).
- Selection set accumulates in the pending pointer; toggling updates the button via `edit_message_reply_markup` and the running count.

### Step C — Propose & create
- Build the PAUSED campaign honoring the operator's audience choice + selected creatives, by parameterizing `build_autonomous_campaign` (new optional args: `audience_override`, `creative_ids`) — when provided, it skips the corresponding auto-pick and uses the operator's choices; when absent, behavior is unchanged (the autonomous path keeps working).
- Show the existing proposal summary with `✅ Approve` / `✖️ Reject` (`agap:approve`/`agap:reject` — the existing, now-working agentic approval).
- Approve → `auto_execute_paused` → PAUSED Meta campaign. The pending pointer is cleared.

## 4. Components & isolation

- **New `backend/guided_campaign.py`** — the flow state machine + step handlers (`start_guided_create`, `handle_audience_choice`, `handle_audience_text`, `render_creatives`, `handle_creative_toggle`, `finalize`). One responsibility: orchestrate the guided creation conversation. Depends on the reuse modules below; holds no Telegram-transport or Meta-API code of its own.
- **`routers/telegram.py`** — thin dispatch: route `gcreate:*` callbacks and the "create campaign" free-text intent to `guided_campaign`. No business logic added here.
- **Reuse (unchanged or minimally extended):** `analysis_engine.rank_audiences_for_next_campaign`, `creative_recommender._best_existing_creatives`, the creative media fetchers + `_send_creative_media` rendering, `opportunity_finder.build_autonomous_campaign` (+ two optional params), `pending_context_store`, `telegram_outbound` (send_photo/send_video/send message + `edit_message_reply_markup`), `execution_service.auto_execute_paused`.

## 5. Error handling

- **Live creative fetch fails** → fall back to the knowledge-base snapshot (existing `_adset_creatives_sync` pattern / `analysis.topAds`); if still none, tell the operator and offer the auto path.
- **Ambiguous audience free-text** → the confirm step lets them re-enter; the agent never silently guesses targeting.
- **Stale / abandoned flow** → the pending pointer has `createdAt`; a guided pointer older than a TTL (e.g. 30 min) is treated as expired → "Let's start over."
- **RBAC** → the whole flow is manager-gated (owner/admin); viewers are blocked at the existing gate. Callbacks correctly identify the human (Step-1 fix).
- **Meta write disabled / guardrail fail** → surfaced exactly as today via `auto_execute_paused`'s `blocked` reason.

## 6. Testing (regression at each step)

- **Unit:** flow state transitions (audience choice → creatives → build); audience free-text → targeting spec; creative toggle add/remove + count; `build_autonomous_campaign` honoring `audience_override`/`creative_ids` vs unchanged auto path when omitted.
- **Integration:** simulate the full callback sequence through `/api/telegram/command` with **realistic payloads** (incl. `callback_query.message.from` = the bot, exercising the RBAC fix), asserting each step's text + inline keyboard + the final proposal + Approve → executed.
- **Regression:** full backend suite green at every step (baseline 540).

## 7. Out of scope

- Per-creative performance editing / new-creative upload (we select among existing creatives only).
- Web-dashboard equivalent of the guided flow (Telegram-only).
- Audience picker from a live Meta interest-search API (free-text parse + known interests only).
- Changing the autonomous/proactive auto-build path (kept intact).
- Deployment (separate; requires explicit operator authorization).
