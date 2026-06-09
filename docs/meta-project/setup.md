# Set up the "Meta Ads Operator" Claude.ai Project

Three files in this folder:
- `instructions.md` — paste into the Project's **Instructions**.
- `knowledge.md` — upload to the Project's **Knowledge**.
- `setup.md` — this guide.

## Prerequisites

- A Claude.ai plan with **custom connectors** (Pro / Max / Team / Enterprise). You're on **Max** ✅.
- The **Meta connector deployed** at a private secret URL `https://82-70-42-188.sslip.io/mcp/<SECRET>`
  (the `/mcp/<SECRET>` endpoint on the VM). Claude will deploy it and give you the exact secret URL.
  Until it's connected, the Project can chat but can't fetch/edit live data.

## Steps

### 1. Connect the Meta tool (after the connector is deployed)
1. claude.ai → **Settings → Connectors → Add custom connector**.
2. Name: `Meta Ads`. URL: `https://82-70-42-188.sslip.io/mcp/<SECRET>` (Claude will give you the
   exact secret URL).
3. Leave **Advanced settings / OAuth EMPTY** — this connector uses a private secret URL, no OAuth.
4. Click **Add**. The Meta tools become available.

Security: the secret URL is your key — don't share it. If it leaks, rotate `MCP_PATH_SECRET` on the
server and re-add the connector with the new URL.

### 2. Create the Project
1. claude.ai → **Projects → Create project**. Name it e.g. **"Shahlo Meta Ads"**.
2. Open the project's **Instructions** (a.k.a. custom instructions) → paste the entire contents of
   `instructions.md`.
3. Open **Knowledge** (or "Add content"/files) → upload `knowledge.md` (or paste its contents).
4. In the project, enable the **Meta Ads** connector for the project (Tools/Connectors toggle).

### 3. Use it
Start a **new chat** in the project for each topic (keeps things uncluttered). Ask anything, e.g.:
- "What campaigns are active right now?"
- "Full setup of the income campaign — audience, interests, placements, A/B?"
- "Best placement by CTR for our top creative, last 30 days."
- "Archive the idle test campaigns I created over a week ago." → it previews → you say "yes".

## Notes

- **Reads are always live** (fresh from Meta). **Reversible edits** apply directly; **destructive
  edits** (archive / pausing an active spender / big budget jumps) are previewed and wait for your
  "yes".
- This Project is separate from the 24/7 Telegram/dashboard agent (which keeps doing proactive
  monitoring, alerts, and autonomous PAUSED test creation). Use whichever is handy.
- If a tool ever fails or isn't connected, the Project will say so rather than guess.
