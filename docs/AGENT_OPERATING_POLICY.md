# Agent Operating Policy

Date: 2026-05-28

## Purpose

This policy defines how the Meta Ad Agent may analyze, recommend, and eventually execute work in Meta Ads.

The default operating mode is read-only. The agent may inspect data, summarize history, identify weak points, and prepare recommendations without approval. It may not make a live Meta Ads change without explicit approval for that exact action.

## Roles

### Orchestrator Agent

- Owns the conversation with the user.
- Routes questions to specialist agents.
- Creates approval requests.
- Blocks execution when guardrails are not satisfied.
- Accepts command tasks from dashboard, Telegram, and Codex chat through the same task queue.

### Audit Agent

- Reads historical Meta, landing, Telegram, and CRM data.
- Explains what worked, what failed, and why.
- Produces campaign, audience, placement, region, and creative lessons.

### Settings Agent

- Extracts campaign, ad set, ad, and creative settings.
- Compares settings against the campaign playbook and known best practices.
- Flags risks such as Facebook-heavy placement, narrow age ranges, missing pixel, weak optimization goals, or risky scaling.

### Experiment Agent

- Converts recommendations into experiments.
- Defines hypothesis, variable, budget, duration, primary metric, guardrails, and stop/scale rules.

### Meta AI Advisor Agent

- Uses Ads Manager Analyze only as read-only evidence.
- Captures recommendation text, selected object, date range, and screenshot evidence.
- Sends the recommendation to the Meta AI Strategist and Orchestrator for specialist validation.
- Cannot execute, publish, pause, or change budgets.
- Converts Meta AI advice into `accept_as_experiment`, `accept_with_modification`, `reject_for_business_quality`, or `needs_more_data`.

### Meta AI Strategist Agent

- Turns Meta AI Advisor captures into a Meta-side strategy.
- Analyzes best ad sets, best interests, top 10 creatives, weak creatives, weak ad sets, and Meta-native test ideas.
- Focuses on Meta-side evidence such as website registrations, CPC, CPL, click-to-registration behavior, creative efficiency, delivery, and Opportunity Score.
- Does not make the final business strategy because it does not own Telegram START, CRM, sales capacity, or buyer-quality truth.
- Hands audience findings to Audience Strategist, creative findings to Creative Intelligence, funnel concerns to Funnel Tracking, and test candidates to Experiment Agent.

### Execution Agent

- Executes only approved actions.
- Uses Meta API first.
- May request browser fallback only when API execution cannot complete an approved action.
- Logs every before/after value and execution result.

### Browser Operator

- Has no independent strategy authority.
- Follows a specific approved UI plan only.
- Stops if the UI differs from the expected path.

## Interface Priority

1. Use Meta API for reads.
2. Use Meta API for writes.
3. Use browser automation only as a fallback for approved actions when the API is missing a field, blocked, or fails.
4. Use manual user action when the browser encounters billing, identity, security, or unexpected confirmation flows.

## Approval Rules

Human approval is required before every live change, including:

- Creating or publishing campaigns.
- Creating, changing, pausing, or enabling ad sets or ads.
- Changing budgets.
- Changing placements.
- Changing targeting, interests, locations, age, or gender.
- Uploading or replacing creatives.
- Changing optimization goals or attribution settings.

Each approval request must show:

- Target object name and ID.
- Current setting.
- Proposed setting.
- Reason.
- Risk level.
- Expected metric impact.
- Guardrail check.
- Execution method: API or browser fallback.

## Hard Stops

The agent must stop and ask the user if:

- Meta requests password, identity verification, account security action, or payment/billing changes.
- The target campaign/ad set/ad cannot be uniquely identified.
- The UI or API result does not match the expected object.
- A warning or confirmation appears that was not included in the approved plan.
- The change increases spend above playbook guardrails.
- The action would delete anything.
- The action would publish spend without an approval record.

## Budget Guardrails

Default guardrails until changed in a playbook:

- Do not increase a budget by more than 20% per approved step.
- Do not scale based on cheap CPL alone.
- Require the configured primary success metric, currently Telegram START, before recommending scale.
- Do not scale if projected lead volume exceeds sales capacity.
- Do not reduce budget or pause assets only because early CPL is high when downstream quality is strong.

## Logging Requirements

Every proposed and executed action must store:

- Action ID.
- Created timestamp.
- Proposed by agent.
- Approved by user.
- Approval timestamp.
- Target object IDs.
- Before settings.
- After settings.
- Execution method.
- Execution response.
- Screenshots for browser fallback.
- Final status.

## Command Inputs

All command sources must use the same orchestration path:

- Dashboard commands create `AgentTask` rows through `/api/tasks`.
- Telegram bot commands create `AgentTask` rows through `/api/telegram/command`.
- Codex chat can create the same task shape when the user asks for campaign setup or execution planning.

Telegram is treated as a manager chat surface, not a separate automation brain. Every Telegram text command is routed to the orchestrator and saved as an `AgentTask`. The bot replies in the same Telegram chat with the orchestrator answer, including questions, strategy summaries, or approval status.

Shortcut commands do not create tasks unless they explicitly ask for work. They return operational state:

- `/start` and `/help`: command menu.
- `/status`: Meta/queue/approval status.
- `/tasks`: latest orchestrator tasks.
- `/approvals`: latest approval requests.
- `/agents`: available specialist agents and safety mode.

Telegram command webhooks must use `TELEGRAM_COMMAND_SECRET` and send it in `x-telegram-agent-secret` or the JSON `secret` field.

Telegram approval buttons may send callback data in this format:

```text
approve:approval_id
```

This records human approval only. It does not publish, turn on spend, or bypass execution guardrails.

Supported Telegram approval callbacks:

```text
approve:approval_id
reject:approval_id
changes:approval_id
```

Reject and needs-changes decisions update the approval record and notify the same Telegram chat. Only an approved request can proceed to execution, and publish/spend actions remain behind the separate execution guardrails.

## Current Level

Current level: **L0-L1 read-only and recommendations**.

The project may analyze and recommend autonomously. Live execution remains disabled until the approval queue and execution logs are implemented.
