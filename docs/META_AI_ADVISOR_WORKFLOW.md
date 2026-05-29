# Meta AI Advisor Workflow

Date: 2026-05-29

## Purpose

Meta AI inside Ads Manager can see platform-side delivery signals that are useful for diagnosis. It should be treated as a read-only advisor, not as the campaign decision-maker.

The Meta AI Advisor Agent captures Meta AI output and gives it to the Orchestrator. The Orchestrator then asks the relevant specialist agents to validate or challenge the recommendation against our business data.

## When To Use Meta AI

Use the Ads Manager Analyze panel when:

- cost changes sharply and the cause is unclear,
- a campaign, ad set, or ad is selected and Meta shows an Analyze button,
- Opportunity Score changes,
- creative fatigue or creative efficiency is suspected,
- delivery is limited, inactive, learning, or under-delivering,
- Meta recommends Advantage+ Audience, placement changes, budget changes, or A/B tests,
- we need a second opinion before approving an experiment.

Do not use Meta AI as the only reason to scale, pause, or publish.

## Capture Flow

1. Browser Operator opens Ads Manager read-only.
2. Select the exact campaign, ad set, or ad.
3. Click Analyze.
4. Capture the visible Meta AI output and screenshot.
5. Store the capture with:
   - selected object ID and name,
   - date range,
   - recommendation text,
   - visible metrics mentioned by Meta AI,
   - screenshot path,
   - capture timestamp.
6. Meta AI Advisor summarizes the recommendation.
7. Orchestrator routes the recommendation to specialist agents.

## Specialist Handoff

- Creative recommendation -> Creative Intelligence Agent.
- Audience recommendation -> Audience Strategist.
- Placement recommendation -> Placement Optimizer.
- Budget or scale recommendation -> Experiment Agent plus Monitoring Agent.
- Tracking, landing, Telegram, CRM recommendation -> Funnel Tracking Agent.
- Publish, pause, budget change, or campaign creation -> Execution Agent after approval.

## Trust Rules

Trust Meta AI more for:

- auction and delivery diagnostics,
- creative efficiency,
- learning or delivery limitations,
- Opportunity Score,
- Meta-native A/B test suggestions,
- broad delivery mechanics.

Trust our agents more for:

- buyer quality,
- Telegram START quality,
- landing-page/VSL/form leak diagnosis,
- CRM and sales follow-up limits,
- Uzbekistan-specific buyer behavior,
- course purchasing power,
- whether cheap leads can become paid students.

## Decision Rule

Every Meta AI recommendation becomes one of these:

- `accept_as_experiment`: good platform advice, but still needs measured test.
- `accept_with_modification`: useful, but adapted to buyer-quality rules.
- `reject_for_business_quality`: likely cheaper delivery but weak buyer quality.
- `needs_more_data`: Meta AI is plausible but funnel/CRM evidence is missing.

No Meta AI recommendation executes directly.
