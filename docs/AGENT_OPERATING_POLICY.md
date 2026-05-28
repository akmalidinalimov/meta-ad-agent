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

## Current Level

Current level: **L0-L1 read-only and recommendations**.

The project may analyze and recommend autonomously. Live execution remains disabled until the approval queue and execution logs are implemented.
