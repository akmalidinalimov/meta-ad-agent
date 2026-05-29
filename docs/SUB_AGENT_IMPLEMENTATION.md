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
