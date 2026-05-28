# Meta Ad Agent Data Model

This document defines the first data contract for the dashboard and the future backend.

## Core Entities

### Campaign

Represents a campaign from Meta or YouTube.

Required fields:

- `id`
- `platform`
- `name`
- `objective`
- `status`
- `dailyBudgetUsd`
- `startedAt`
- `endedAt`

### Ad Set

Represents targeting, placements, and optimization settings.

Required fields:

- `id`
- `campaignId`
- `name`
- `status`
- `ageMin`
- `ageMax`
- `genders`
- `locations`
- `interests`
- `placements`
- `optimizationGoal`

### Ad

Connects an ad set to a creative.

Required fields:

- `id`
- `adSetId`
- `creativeId`
- `name`
- `status`

### Creative

Represents the actual ad asset and message.

Required fields:

- `id`
- `adId`
- `name`
- `format`
- `theme`
- `hookType`
- `primaryPersona`
- `cta`
- `assetUrl`

### Creative Analysis

Represents Gemini/OpenAI/video-analysis output.

Required fields:

- `creativeId`
- `viralScore`
- `buyerIntentScore`
- `courseFitScore`
- `hookSummary`
- `conversionRisk`
- `recommendedAction`

## Daily Metrics

Each row should represent one day, one ad, one creative, and one placement.

Required fields:

- `date`
- `campaignId`
- `adSetId`
- `adId`
- `creativeId`
- `placement`
- `spendUsd`
- `impressions`
- `clicks`
- `landingPageViews`
- `leads`
- `telegramSubscribers`
- `webinarAttendees`
- `purchases`
- `purchaseRevenueUsd`

## Funnel Events

For high-quality attribution, the backend should also store event-level records:

- `ad_impression`
- `ad_click`
- `landing_visit`
- `lead`
- `telegram_subscriber`
- `webinar_attendee`
- `buyer`

Every event should preserve available attribution:

- `campaignId`
- `adSetId`
- `adId`
- `creativeId`
- `fbclid`
- `utm_source`
- `utm_campaign`
- `utm_content`
- `telegramUserId`
- `landingSessionId`
- `occurredAt`
- `valueUsd`

## Next Integrations

1. Meta Marketing API read-only import.
2. Landing page pixel and server-side Conversions API events.
3. Telegram bot subscription and engagement events.
4. Webinar attendance and purchase import.
5. Gemini creative analysis for videos/images.
