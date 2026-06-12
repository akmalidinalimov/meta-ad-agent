# Meta Ad Agent — Session Handoff

_Last updated: 2026-06-11. Read this whole file first, confirm you can reach the codebase + the live deployment, then ask the operator what to build next._

---

## 1. What this is

A strategic, proactive Meta (Facebook/Instagram) **ad agent** for an online AI-course business
(Shahlo's course; market: **Uzbekistan**; Instagram-first; funnel = ad → free lesson/webinar →
**Telegram bot START** → course sale). It watches the live ad account on a schedule, produces
approval-ready suggestions, answers questions, and now **takes live actions** (gated). Two operator
front-ends share one backend brain: a **Telegram bot** and a **web dashboard**. There is also a
**Claude.ai Project MCP connector** as a third, interactive front-end. Reasoning model:
**Claude Opus 4.8** (`claude-opus-4-8`).

Originally "suggest-only"; it has since gained **gated live writes** (approve → dry-run → apply, or
direct for reversible changes), **autonomous PAUSED test-campaign creation**, and **role-based access**.

---

## 2. Where the code lives

- **Worktree (source of truth):** `C:\Users\akmal\Documents\meta-ad-agent-review`
- **Active branch:** `feat/rbac-roles` (HEAD `aa5e00b`) — **the most complete branch**, pushed to
  `origin`. Contains everything: all review rounds + agentic Telegram chat + MCP connector + RBAC.
- **Branch lineage:** `feat/review-improvements` (rounds 1–2, drill-downs, autonomy, agentic chat,
  MCP) → branched into `feat/rbac-roles` (owner/admin/viewer roles). Both on GitHub.
- **Remote:** `https://github.com/akmalidinalimov/meta-ad-agent.git`
- **Nominal main:** `codex/meta-agent` (old, `89d2897`). **The feature branches are NOT merged into
  it.** The primary checkout `C:\Users\akmal\Documents\Meta Ad Agent` sits on this old branch —
  ignore it; use the worktree above.
- Backend: Python 3.11 / FastAPI in `backend/`. Frontend: Vite + React 19 + TS in `src/`.

> **Loose end:** feature work lives only on `feat/*` branches. If you want a single mainline, merge
> `feat/rbac-roles` → `codex/meta-agent` (or open a PR). Not done yet by operator choice.

---

## 3. Live deployment (Oracle Cloud VM)

- **SSH:** `ssh -i ~/.ssh/oci.key opc@82.70.42.188` (Oracle Linux 9, ~512 MB RAM + swap; **too small
  to build** — build locally, copy up). Note the harmless post-quantum SSH warning.
- **App dir:** `/home/opc/meta-ad-agent`  (secrets in `.env`, chmod 600 — **never print them**).
- **Services (systemd):** `meta-ad-agent` (uvicorn on `127.0.0.1:8000`, run by `/usr/bin/python3.11`)
  and `caddy` (HTTPS reverse proxy, 80/443). Unit: `/etc/systemd/system/meta-ad-agent.service`.
- **Dashboard URL:** https://82-70-42-188.sslip.io  (sslip.io magic DNS → the IP).
- **Browser login password:** env `DASHBOARD_PASSWORD` (logs in as **owner**). Inside Telegram there
  is no password (Telegram initData auth).
- **Key env on the VM** (don't print values): `REASONING_PROVIDER=anthropic`,
  `ANTHROPIC_MODEL=claude-opus-4-8`, `META_LIVE_WRITES_ENABLED=true`, `DASHBOARD_SESSION_AUTH=true`,
  `MONITORING_SCHEDULER_ENABLED=true`, `TELEGRAM_ADMIN_CHAT_ID` (= the **owner**, currently
  `6542876935`), `TELEGRAM_COMMAND_SECRET`, `SESSION_SECRET`, `DASHBOARD_PASSWORD`,
  `PUBLIC_DASHBOARD_URL`, plus Meta + Telegram + Anthropic keys. No `MEMBERS_STORE_PATH` (uses default).
- **MCP connector:** mounted at `/mcp/<MCP_PATH_SECRET>/mcp` (secret path is the auth boundary; DNS
  rebinding protection disabled so Caddy's forwarded Host passes). Used by the Claude.ai Project.

### Deploy procedure (build local → copy → restart)
1. Frontend change: `cd <worktree> && npm run build` → outputs `dist/`.
2. `tar czf /tmp/x.tar.gz backend/<changed .py files> dist`  (only the files you changed; never tar
   `backend/storage/` — that holds live JSON state, incl. `members.json`).
3. `scp -i ~/.ssh/oci.key /tmp/x.tar.gz opc@82.70.42.188:/tmp/`
4. On VM: `cd ~/meta-ad-agent && tar xzf /tmp/x.tar.gz && sudo systemctl restart meta-ad-agent`
5. Health: `curl -s http://127.0.0.1:8000/api/health` → `{"status":"ok"}`; tail `sudo journalctl -u
   meta-ad-agent -n 20 --no-pager`.

> **Production deploy / restart requires EXPLICIT operator authorization each time** (the safety
> classifier blocks an ambiguous "yes"). Build + test first, then confirm the restart in plain words.

---

## 4. How to test

- **Backend (CI parity — the local `.env` has live keys, so blank them):**
  `ANTHROPIC_API_KEY="" OPENAI_API_KEY="" REASONING_PROVIDER="" python -m pytest backend/ -q`
  → currently **522 passing**.
- **Frontend:** `npm test -- --run` (vitest, **51 passing**), `npm run lint`, `npm run build` (all
  must pass). DOM tests need `// @vitest-environment jsdom` at the top; jest-dom matchers are NOT
  globally set up — assert with `.toBeTruthy()`, not `toBeInTheDocument()`.
- **Telegram simulation (no real client needed):** POST `/api/telegram/command` with JSON
  `{"secret": "<TELEGRAM_COMMAND_SECRET>", "chat_id": <id>, "user_id": <id>, "text": "..."}` (or a
  `callback_query` object). Run it from the VM so secrets stay there (read `.env` in Python; do NOT
  shell-interpolate the secret — a stray control char causes a 422). Real replies land in that
  Telegram chat.

---

## 5. What's LIVE right now (capabilities)

- **Proactive engine:** daily opportunity suggestions + 4-hourly monitoring; approval cards to web +
  Telegram; 4-hour KPI digest; KPI targets flag ✅/⚠️.
- **Live Meta reads everywhere:** chat/menus pull live campaigns/ad sets/ads/insights (60s TTL cache,
  snapshot fallback). Distinguishes truly-delivering vs ACTIVE-but-past-stop-time.
- **Telegram drill-downs:** 📁 Campaigns → ad sets → **ranked creatives** (spend/impr/clicks/CTR/
  results, thumbnails, video links); 📝 Pending Approvals; inline creative media; emoji formatting.
- **Gated live writes (web + Telegram):** Approve → Dry-run → Apply-live creates a **PAUSED** Meta
  campaign. Already created real paused campaigns.
- **Autonomous campaign creation:** "create a test campaign on your own" → builds best-guess (top-3
  untested audiences, mirrored winning template, up to 5 creatives/ad set) and **auto-creates PAUSED**
  in Ads Manager (gated by guardrails + `META_LIVE_WRITES_ENABLED`).
- **Live campaign introspection:** objective, A/B status, audiences (incl. custom-audience names),
  interests, placements, age/geo, billing/bid, dynamic creative — from live config.
- **Bulk manage:** "archive/pause the idle campaigns you created" → resolves the set, lists, gates on
  approve (button or type "approve"), executes (delete = ARCHIVE, reversible; never touches an active
  deliverer unless named).
- **Agentic free-text Telegram chat (`backend/agentic_chat.py`):** real Anthropic tool-use loop, no
  templates. Reversible writes (pause, archive, budget cuts) apply directly; spend-increasing
  (activate, big budget raise, create-live) require proposal → approve (inline buttons or type
  "approve"). Verified end-to-end.
- **Claude.ai Project MCP connector:** granular live-Meta tools (list/get/insights/creatives/search/
  account_summary + gated update_status/update_budget). Project instructions/knowledge in
  `docs/meta-project/`.
- **RBAC (owner/admin/viewer) — newest, deployed 2026-06-11:** see §6 / the `meta-ad-agent-rbac-state`
  memory. Owner seeded from `TELEGRAM_ADMIN_CHAT_ID`; add admins/viewers from Telegram **👥 Team** or
  web **Settings → Team**; viewers read-only; unknown users denied.

---

## 6. Key files by subsystem

- **Telegram:** inbound/dispatch `backend/routers/telegram.py`; menus/keyboards `backend/telegram_menus.py`;
  outbound `backend/telegram_outbound.py`; startup menu reg `backend/telegram_setup.py`; digest
  `backend/telegram_digest.py`; command parsing `backend/telegram_commands.py`; humanized text
  `backend/telegram_service.py`.
- **Agentic brain:** `backend/agentic_chat.py` (tool-use loop, action policy, `execute_pending`).
- **Chat / reasoning:** `backend/routers/agents.py` (`agent_chat`, routing), `backend/llm_reasoner.py`,
  `backend/llm_provider.py` (Anthropic/OpenAI seam), `backend/chat_service.py`,
  `backend/agent_orchestrator.py`, `backend/chat_campaign_planner.py`.
- **Campaign answers:** `backend/campaign_specific_analysis.py` (roster + config answers + shared
  `format_*` helpers), `backend/campaign_manage.py` (bulk manage), `backend/opportunity_finder.py`
  (`build_autonomous_campaign`).
- **Meta data:** `backend/meta_client.py` (async fetchers incl. `get_entity_insights`,
  `get_adstudies`, `get_saved_audiences`, `get_ads_for_adset`), `backend/meta_live.py` (LiveAccount +
  TTL cache + helpers), `backend/adset_creatives.py` (ranking).
- **Execution/safety:** `backend/meta_execution.py` (`assert_executable`, campaign creation, manage
  exec), `backend/execution_service.py` (`auto_execute_paused`), `backend/routers/approvals.py`,
  `backend/approval_store.py`, `backend/pending_context_store.py` (cross-turn approve state).
- **RBAC:** `backend/members_store.py` (members JSON + owner seed + protection),
  `backend/access_control.py` (role→capability), `backend/routers/members.py` (web CRUD),
  `backend/webapp_auth.py` (`session_role`/`session_subject`, store-based `user_allowed`),
  `backend/routers/auth.py` (login → owner; `/api/auth/session` returns role), `backend/app.py`
  (session guard: 401 unauth, 403 viewer mutations). Frontend:
  `src/components/dashboard/views/TeamPanel.tsx`, `src/services/members.ts`,
  `src/components/Dashboard.tsx` (+ `src/App.tsx` role bootstrap).
- **MCP:** `backend/mcp_server.py` (FastMCP server, tools, mount path). Mounted in `backend/app.py`.
- **Auth/session:** `backend/webapp_auth.py`, `backend/routers/auth.py`, session-guard middleware in
  `backend/app.py`.
- **Funnel/event ingest (student side):** `backend/chatplace_events.py`, docs
  `docs/FUNNEL_EVENT_TRACKING.md` (ChatPlace = the student bot platform; this repo only ingests
  milestone events for funnel attribution).
- **Docs:** `docs/superpowers/specs/` + `docs/superpowers/plans/` (RBAC + connector specs/plans),
  `docs/meta-project/` (Claude.ai Project instructions/knowledge/setup), `docs/DEPLOY_ORACLE.md`
  (older Docker variant — the live VM uses **systemd**, not Docker; trust this HANDOFF over that doc).

---

## 7. Known limitations & deferred items

- **Purchases / ROAS not tracked** — only leads + Telegram STARTs. ROAS-aware analysis is pending an
  operator-side pixel/purchase-tracking activation, then code wiring. See `meta-ad-agent-signals-state`.
- **Autonomous refinement adjusts budget only** — a follow-up like "make it Tashkent-only, age 25-34"
  is acknowledged but re-ranked from data, not applied as an override. (Candidate next feature.)
- **Two operator front-ends overlap** (Telegram agentic chat + Claude.ai Project) — both intentional.
- **No CI** in the repo; tests are run manually with the env-blanking command in §4.
- **Frontend bundle > 500 kB** (single chunk) — pre-existing warning, not blocking.

---

## 8. Gotchas (will bite you if forgotten)

- **Production restart needs explicit per-action authorization** (see §3).
- **Never tar/overwrite `backend/storage/`** on deploy — it holds live JSON state (`members.json`,
  approvals, pending context, knowledge base).
- **CI-parity test env:** blank `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/`REASONING_PROVIDER` or ~5 "no-key"
  tests fail locally because the local `.env` has live keys.
- **VM Python is `/usr/bin/python3.11`** (has httpx etc.); a bare `python3` lacks deps.
- **Telegram initData HMAC** includes the `signature` field in the data-check-string (only `hash` is
  excluded) — do not drop `signature` or real Mini App logins break.
- **Insights:** use `get_entity_insights(config, object_id, ...)` for scoped breakdowns; account-wide
  is paginated/capped. Aggregate with `time_increment=None` (per-day rows blow past Telegram limits).
- **Telegram message limit 4096 chars** — `clamp_telegram_text` guards; inline web_app/video buttons
  need absolute URLs.
- **RBAC:** access is now managed **in-app** (Team panel), not via the `.env` allowlist (that's only a
  one-time seed). Owner = `TELEGRAM_ADMIN_CHAT_ID`, immutable.

---

## 9. Housekeeping / open threads

- `feat/rbac-roles` is pushed but **not merged to a mainline** — decide whether to merge/PR.
- A stale build tarball may sit at `/tmp/rbac.tar.gz` on the VM — harmless, can be deleted.
- A student-facing **recognition/gamification copy** task was discussed then **discarded** (it was
  meant for another chat) — not part of this codebase; ignore any reference to it.
- The `docs/DEPLOY_ORACLE.md` Docker guide is **outdated** vs the live systemd setup.

---

## 10. Project memory (auto-loaded each session)

`C:\Users\akmal\.claude\projects\C--Users-akmal-Documents-Meta-Ad-Agent\memory\` — index `MEMORY.md`:
- `meta-ad-agent-rbac-state` — roles live on both surfaces (this round).
- `meta-ad-agent-autonomy-state` — autonomous PAUSED creation, introspection, bulk manage, agentic TG chat.
- `meta-ad-agent-signals-state` — Telegram START live; purchases/ROAS deferred.
- `meta-ad-agent-mcp-connector` — Claude.ai Project connector (secret-URL MCP).

---

## 11. First moves for the new session

1. `cd C:\Users\akmal\Documents\meta-ad-agent-review` and confirm branch `feat/rbac-roles`.
2. `ssh -i ~/.ssh/oci.key opc@82.70.42.188 "systemctl is-active meta-ad-agent && curl -s http://127.0.0.1:8000/api/health"`.
3. Run the backend + frontend test commands in §4 to confirm a green baseline.
4. Ask the operator what "something more profound" means and scope it (brainstorm → spec → plan →
   parallel worktree agents → test → deploy-on-authorization — the established workflow).
