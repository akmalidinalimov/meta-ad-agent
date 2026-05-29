# Meta Execution Safety

Date: 2026-05-29

## Baseline

The agent can have API permissions and still remain safe. Permissions define what is technically possible; this document defines what is allowed.

## API-First Execution

The Execution Agent must use the Meta Marketing API first for any approved change.

API execution is preferred because it is:

- auditable,
- repeatable,
- easier to test,
- less fragile than browser clicks,
- easier to rollback or compare before/after.

Current implementation status:

- The dashboard can prepare approval requests for paused campaign structures.
- Generated campaigns and ad sets are always `PAUSED`.
- Dry-run execution is implemented and does not send any request to Meta.
- Live Meta write execution is intentionally disabled until the final confirmation endpoint and execution logs are reviewed.

## Browser Fallback

Browser fallback is allowed only when all of these are true:

- The exact action is already approved.
- API execution failed or the required field is UI-only.
- The target campaign/ad set/ad ID is known.
- The Browser Operator has a step-by-step plan.
- A screenshot is captured before and after.
- The operator can stop before final publish/confirm if anything unexpected appears.

Browser fallback is not allowed for:

- billing,
- payment methods,
- account ownership,
- identity verification,
- password or security flows,
- deletion,
- broad account settings,
- unapproved publishing.

## Execution Decision Tree

```text
Need data?
-> Use Meta API.
-> If missing, inspect dashboard/browser read-only.

Need live change?
-> Prepare proposed action.
-> Check playbook guardrails.
-> Ask approval.
-> Dry-run the exact payload.
-> If approved, try Meta API.
-> If API succeeds, log result.
-> If API fails, propose browser fallback.
-> If browser fallback approved, execute exact steps.
-> If UI differs, stop and ask user.
```

## Required Proposed Action Shape

```json
{
  "actionType": "budget_change | pause_ad | enable_ad | placement_change | targeting_change | create_draft",
  "target": {
    "level": "campaign | adset | ad | creative",
    "id": "string",
    "name": "string"
  },
  "before": {},
  "after": {},
  "reason": "string",
  "risk": "low | medium | high",
  "expectedImpact": "string",
  "guardrailResult": "pass | warn | fail",
  "guardrailChecks": [],
  "executionMethod": "api | browser_fallback",
  "status": "needs_review | approved | dry_run_completed | executed | blocked",
  "requiresApproval": true
}
```

## Initial Allowed Actions After Approval

For Version 1.0, allowed actions should start narrow:

- create draft campaigns,
- create draft ad sets,
- prepare creative upload drafts,
- change budgets within playbook limits,
- pause clearly underperforming ads/ad sets,
- enable approved drafts,
- adjust placements for approved ad sets.

## Initial Blocked Actions

- deleting campaigns/ad sets/ads,
- changing billing or payment,
- changing account access,
- increasing total daily budget above the configured maximum,
- changing attribution settings without a separate warning,
- broad account-level changes.

## Fallback Prompt For Browser Operator

```text
You are the Browser Operator for Meta Ads Manager.
You do not decide strategy.
You only execute an approved UI plan.
Before clicking a final publish, confirm, pause, or budget-save action, verify that the target object ID/name and before/after settings match the approved action.
If anything differs, stop and report the mismatch.
Do not touch billing, payment, security, identity, or account ownership settings.
```
