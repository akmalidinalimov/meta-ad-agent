# Agent Office V2 Animation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the static Agent Office with a clearer top-view animated office where agents visibly move between desks as they critique and refine a Meta campaign strategy.

**Architecture:** Keep the existing council API and session data. Add frontend replay state that steps through council events on a timer, computes speaker/listener desk coordinates, and renders one moving agent avatar plus active desks, round status, and final plan. Use CSS only for the office scene, animation, desk visuals, and responsive layout.

**Tech Stack:** React, TypeScript, CSS animations, existing FastAPI council endpoint, Playwright E2E.

---

### Task 1: Agent Office Replay State

**Files:**
- Modify: `src/components/Dashboard.tsx`

- [ ] Add replay state to `AgentOfficeView`: `activeEventIndex`, `isPlaying`, and timer effect.
- [ ] Reset replay to the first event whenever a new council session arrives.
- [ ] Add playback buttons: `Play`, `Pause`, `Step back`, `Step forward`.
- [ ] Calculate `activeEvent`, `activeRound`, moving agent position, and destination position from the active council event.

### Task 2: Top-View Office Scene

**Files:**
- Modify: `src/components/Dashboard.tsx`
- Modify: `src/App.css`

- [ ] Replace the static grid-like office map with a top-view office scene.
- [ ] Render each desk at fixed percentage coordinates with labels, laptop, chair, and status light.
- [ ] Render one moving agent avatar that travels from `fromAgent` desk to `toAgent` desk using CSS variables.
- [ ] Highlight the speaking desk, receiving desk, and current round.
- [ ] Show the active question and answer beside the office scene.

### Task 3: Clarity And UX

**Files:**
- Modify: `src/components/Dashboard.tsx`
- Modify: `src/App.css`

- [ ] Add a plain-language “What is happening now” strip.
- [ ] Add “Timeline replay” showing all council events with the active event highlighted.
- [ ] Keep the final plan visible after the replay so the user can inspect decisions.
- [ ] Keep publish safety visible: paused draft allowed, publish blocked, approval required.

### Task 4: Verification

**Files:**
- Modify: `tests/e2e/dashboard.spec.ts`

- [ ] Update the Agent Office E2E assertions to check the top-view office, playback controls, active exchange, and final plan.
- [ ] Run `npm test -- --run`.
- [ ] Run `npm run lint`.
- [ ] Run `npm run build`.
- [ ] Run `npm run test:e2e`.
- [ ] Run an in-app browser smoke check for the Agent Office tab.
- [ ] Commit and push `codex/meta-agent`.
