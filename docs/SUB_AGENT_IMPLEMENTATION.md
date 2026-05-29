# Sub-Agent Implementation

Date: 2026-05-29

## Current Layer

The project now has a lightweight orchestrator layer in code.

File:

- `backend/agent_orchestrator.py`

The orchestrator does not create separate long-running processes yet. It defines the specialist responsibilities, routes chat intent, and blocks execution unless a future approval request exists.

## Specialist Registry

Configured specialists:

- Orchestrator Agent
- Audit Agent
- Audience Strategist
- Creative Intelligence Agent
- Placement Optimizer
- Funnel Tracking Agent
- Monitoring Agent
- Experiment Agent
- Meta Execution Agent
- Browser Operator

Each specialist has:

- Purpose
- Inputs
- Outputs
- Tool boundary
- Execution permission
- Approval requirement

API:

```text
GET /api/agents
```

## Chat Routing

The chat endpoint now checks the orchestrator first for:

- Sub-agent / role questions
- Campaign setup / campaign plan requests
- Execution / browser fallback requests
- Meta AI Analyze panel capture and validation requests
- Meta AI capture-to-strategy requests

If the orchestrator can handle the request, it returns:

- `activeAgent`
- `routeReason`
- `answer`
- `sources`
- `suggestedQuestions`

If the orchestrator does not need to intervene, chat falls back to the existing knowledge-base and LLM analysis path.

## Execution Safety

Current execution level remains read-only:

- The Execution Agent cannot change Meta Ads yet.
- Browser fallback cannot operate independently.
- The agent can draft an approval request.
- Live Meta writes require a future approval queue and execution log.

Execution rule:

1. Meta API first.
2. Browser fallback only if API cannot complete an already approved action.
3. Stop if Meta shows billing, security, identity, unexpected confirmation, or ambiguous target state.

## Next Step

Build Chat-to-Campaign Planner:

- User describes the campaign in chat.
- Orchestrator creates a structured playbook from natural language.
- Strategy Generator turns the playbook into budget, audience, placement, creative, risk, and approval cards.
- User approves specific actions.

This is the bridge between conversation and future Meta execution.

## Chat-to-Campaign Planner

Implemented in:

- `backend/chat_campaign_planner.py`

The planner can turn a clear chat brief into a local draft campaign playbook. Example:

```text
Create a campaign with 3 VSLs: earning money, business automation, content creators. Use $100 each and optimize for Telegram START.
```

The generated playbook includes:

- Arbitrary number of segments/VSLs
- Segment IDs and names
- Budget per segment
- Primary success metric
- Uzbekistan/Tashkent-style location inference
- Instagram Reels, Stories, and Feed placements by default
- Audience notes, pain points, offer angles, interests, age range, guardrails

When the chat endpoint receives a complete campaign brief, it saves the generated playbook locally so it becomes available in the dashboard Strategy view. This is still a draft only. No Meta Ads changes are executed.
