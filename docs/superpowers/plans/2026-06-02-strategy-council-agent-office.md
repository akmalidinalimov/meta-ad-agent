# Strategy Council Agent Office Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a proactive multi-agent strategy council and show its agent-to-agent work visually in the dashboard.

**Architecture:** Add a focused backend `agent_council.py` module that creates deterministic council sessions with specialist questions, critiques, revisions, scores, and a final approval-safe campaign plan. Expose the council through `/api/agent/council` and attach council sessions to chat/task responses when campaign strategy requests need multi-agent reasoning. Add a dashboard Agent Office panel that renders active agents, handoffs, critique rounds, and final decisions as an animated 2D office-style visualization.

**Tech Stack:** FastAPI, Python test suite, React/Vite/TypeScript, existing dashboard CSS, existing agent registry and strategy generator.

---

### Task 1: Backend Council Model

**Files:**
- Create: `backend/agent_council.py`
- Test: `backend/test_agent_council.py`

- [ ] Create `run_strategy_council(question, knowledge, playbooks)` returning a session object with `agents`, `rounds`, `handoffs`, `scores`, `finalPlan`, `quality`, and `approvalRequired`.
- [ ] Include specialist agents: orchestrator, audit, audience, creative, placement, funnel, experiment, monitoring, meta_ai_strategist, execution.
- [ ] Add at least three rounds: initial recommendations, cross-agent critique, final synthesis.
- [ ] Ensure final plan includes campaign naming, audience, creative, placement, funnel tracking gaps, experiment plan, monitoring cadence, and paused execution readiness.
- [ ] Test that the session has at least 9 agents, at least 10 inter-agent events, average score >= 9.5, and approval is required.

### Task 2: API And Chat Integration

**Files:**
- Modify: `backend/app.py`
- Modify: `src/services/agentChatProvider.ts`
- Modify: `src/types/marketing.ts`
- Test: `backend/test_agent_chat_api.py` or `backend/test_agent_council.py`

- [ ] Add `CouncilRequest` and `POST /api/agent/council`.
- [ ] Attach `agentCouncil` to chat responses when a campaign strategy/council command is detected.
- [ ] Preserve existing approval safety: no live execution from council output.
- [ ] Test the API returns council rounds, scores, and a final plan.

### Task 3: Dashboard Agent Office

**Files:**
- Modify: `src/components/Dashboard.tsx`
- Modify: `src/App.css`

- [ ] Add an `Agent Office` nav item.
- [ ] Add an `AgentOfficeView` with a command field and “Run council” button.
- [ ] Render agent seats/tables in a 2D office layout with active pulse states.
- [ ] Render handoff lines/events showing agent-to-agent communication.
- [ ] Show round transcript, agent scores, final plan, and execution safety.
- [ ] Feed the latest chat council session into the visual office when chat triggers it.

### Task 4: Verification

**Files:**
- Existing tests plus e2e.

- [ ] Run `python -m pytest backend -q`.
- [ ] Run `npm test -- --run`.
- [ ] Run `npm run lint`.
- [ ] Run `npm run build`.
- [ ] Run `npm run test:e2e`.
- [ ] Commit and push the verified branch.

