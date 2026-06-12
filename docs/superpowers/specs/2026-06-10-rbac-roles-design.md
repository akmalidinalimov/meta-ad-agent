# Role-Based Access Control (owner / admin / viewer) — Design

**Goal:** Replace the flat env allowlist with a managed members system so the owner and admins can add people and assign roles from BOTH the Telegram bot and the web platform. Viewers are read-only ("watch", no chat, no writes). Unknown users who launch the bot are told they have no access.

**Date:** 2026-06-10
**Status:** Approved (chat), proceeding to implementation.

---

## Decisions (confirmed with operator)

1. **Viewer = "see dashboards, no chat."** Viewer can use read-only menu buttons (KPIs, Status, Alerts, Campaigns drill-down, Pending — view only) and open the web dashboard read-only. The agentic free-text chat does NOT engage them; all writes/approvals are blocked. Free-text from a viewer gets ONE short canned notice, not silence.
2. **Role management = owner + admins; owner protected.** Admins have the same rights as the owner, including adding/removing members and assigning roles. The Owner can never be demoted or removed by anyone. Admins MAY manage other admins/viewers.
3. **Add method = by `@username` or numeric Telegram ID.** Operator proactively adds someone; on their first `/start` they are matched and their numeric `userId` is pinned. Unknown users get the no-access message (no self-service request flow).
4. **Both surfaces.** Roles gate the Telegram bot AND the web dashboard. Adding/assigning works from both. Shared dashboard password still logs in as Owner.

---

## Architecture

A single JSON members store is the source of truth; a pure policy module decides capabilities; both surfaces (Telegram, web) consult them. Mirrors the existing file-store convention (`approval_store.py`, `pending_context_store.py`).

### 1. `backend/members_store.py` (new)
- Storage: `storage/members.json`. Member record: `{ "userId": str|None, "username": str|None, "role": "owner"|"admin"|"viewer", "addedBy": str, "addedAt": iso8601 }`.
- **Owner seed:** on first load, `TELEGRAM_ADMIN_CHAT_ID` is inserted as `role="owner"`. The owner is immutable.
- **Back-compat migration:** if the store is empty on first load, every id in `TELEGRAM_ALLOWED_USER_IDS` is imported as `admin`. Existing access keeps working at deploy.
- Username normalized: lowercased, leading `@` stripped. Match priority: `userId` exact; else `username`. When a username-only member first messages, their `userId` is pinned (and persisted).
- API:
  - `list_members() -> list[dict]`
  - `resolve(user_id, username) -> dict | None` (also pins userId on first username match)
  - `add_member(*, user_id=None, username=None, role, added_by) -> dict` (role in {admin, viewer}; dedupe by id/username → updates role)
  - `set_role(member_key, role, *, actor) -> dict` (raises on owner)
  - `remove_member(member_key, *, actor) -> None` (raises on owner)
  - `is_owner(user_id) -> bool`
- Owner-protection and "role must be admin|viewer for non-owner" enforced inside the store (raises `ValueError`).

### 2. `backend/access_control.py` (new, pure, no I/O)
- `ROLES = ("owner", "admin", "viewer")`.
- Capability table:
  - `view` → owner, admin, viewer
  - `act` → owner, admin   (chat, any Meta write, approvals)
  - `manage_team` → owner, admin
- `role_for(user_id, username) -> str | None` (thin wrapper over `members_store.resolve` returning the role string or None).
- `can(role, capability) -> bool`.
- `is_manager(role) -> bool` (role in {owner, admin}).

Every gate in both surfaces asks `can(...)`, so no write path is missed.

### 3. Telegram bot (`telegram_service.py`, `routers/telegram.py`, `telegram_menus.py`)
- Replace `telegram_command_allowed` with role resolution. The command handler resolves the role once up front:
  - **None (unknown):** reply once "🚫 You don't have access to this bot. You can leave." → return. No menu, no further processing.
  - **viewer:** allow read-only menu buttons + read-only drill-down callbacks (`cmp:*`, `apv:*` view, KPIs/Status/Alerts). Block: free-text agentic (canned notice), and all write/approve callbacks (`approve`, `dryrun`, `applylive`, `cancel`, `reject`, `changes`, `agap`, `manage`, plus any set_status/set_budget). Viewer reply keyboard omits 💬 Ask and 👥 Team.
  - **admin/owner:** full current behavior + 👥 Team panel.
- **Team panel** (managers only): reply button `👥 Team` → `team:list` showing each member (name/username + role; owner row locked). Inline actions: `➕ Add` (`team:add` → `pending_context` kind `team_add` captures the next message: parse `@username` or numeric id, then a role choice via inline buttons `team:setrole:<key>:<role>`), change role, `team:remove:<key>`. All `team:*` handlers re-check `is_manager` and owner-protection.
- Central enforcement: a single `_role_allows_action(role, action)` consulted before dispatching any write callback, so adding a new write path later can't bypass the gate.

### 4. Web platform (`routers/members.py` new, `webapp_auth.py`, `app.py`, frontend)
- `backend/routers/members.py`: `GET /api/members` (managers), `POST /api/members` (add by username/id + role), `PATCH /api/members/{key}` (role), `DELETE /api/members/{key}` — all require `manage_team` read from the session role; owner-protection via the store.
- `webapp_auth.py`: resolve the role at login and embed it in the signed session payload. Password login → `owner`. Telegram Mini App login → that user's role; unknown Telegram user → 401 with the no-access message.
- Session-guard / mutation API routes require `act`; viewers get read-only (mutations → 403).
- Frontend: **Settings → Team** panel (list members, add by `@username`/ID with a role select, change role, remove; owner row locked). For viewers: hide write controls (approval buttons, chat composer), show a "Viewer · read-only" badge. Role is read from the existing auth/session bootstrap (`/api/auth/session` or equivalent).

---

## Error handling
- Unknown user → polite no-access (bot) / 401 (web).
- Member removed mid-session → next action re-resolves from the store and is denied.
- Demote/remove owner → store raises `ValueError`; surfaces show "The owner can't be changed."
- Add duplicate (same id/username) → updates the existing member's role instead of creating a second row.
- Add by username with no `@`/invalid id → validation error surfaced to the operator.

## Testing
- `members_store`: CRUD; owner seed from env; owner-protection (demote/remove raises); env `TELEGRAM_ALLOWED_USER_IDS` migration; username normalization; userId pinning on first match; duplicate-add updates role.
- `access_control`: capability truth table for all three roles + None.
- Telegram gate: unknown → no-access + no processing; viewer → menu allowed, free-text blocked (canned notice), write callback blocked; admin → full; team panel visible only to managers; team add/role/remove happy paths + owner-protection + non-manager 403.
- Members API: viewer/none forbidden (403/401), admin allowed, owner-protected, add-by-username and add-by-id.
- `webapp_auth`: role embedded in session; password→owner; Telegram unknown→rejected; viewer mutation→403.
- Frontend: viewer hides write controls + shows badge; manager sees Team panel; add/remove member calls the API.

## Back-compat & rollout
- Env allowlist remains a seed/fallback; no `.env` change required to deploy. The owner (`TELEGRAM_ADMIN_CHAT_ID`) and current allowed users keep working immediately, now as owner/admins.
- `storage/members.json` is created on first load; persists across restarts like other stores.
