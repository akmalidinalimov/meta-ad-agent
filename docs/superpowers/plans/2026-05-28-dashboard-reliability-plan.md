# Dashboard Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing Meta Ad Agent dashboard trustworthy before adding new CRM, ChatPlace, and execution features.

**Architecture:** Keep the current React/Vite frontend and FastAPI backend. Add focused analytics tests first, then repair the dashboard data contract, campaign/date filtering, creative ranking, media display rules, and chat request state. Keep Meta write actions out of scope.

**Tech Stack:** React 19, TypeScript, Vite, Recharts, FastAPI, Python, pytest, Vitest.

---

## Scope

This plan implements Version 0.2 from `docs/ARCHITECTURE_AND_VERSION_ROADMAP.md`.

In scope:

- Dashboard date filtering must only show campaigns and metrics inside the selected 7/30/90 day window.
- Multi-campaign selection must work without creating false "No matching data" states.
- Creative scores must be ranked and displayed in score order.
- The dashboard must expose first-pass rankings for creatives, audiences/ad sets, campaigns, placements, and segments where current data supports it.
- Creatives must preserve campaign/ad set/ad attribution from Meta data.
- Thumbnails should show where available.
- Videos should only be presented as playable when a real video source URL exists.
- Refresh/chat loading states should not get stuck.
- Waste/recommendation rows should be deduplicated.
- Creative media cards should clearly separate thumbnail-only assets from playable videos.

Out of scope:

- Creating Meta campaigns.
- ChatPlace integration.
- Bitrix24/Google Sheet import.
- Scheduled 4-hour monitoring.
- Full creative video AI analysis.
- Telegram approval bot.
- Budget execution.

## File Structure

- Modify: `src/lib/analytics.ts`
  - Owns pure calculations for funnel, trends, creative scoring, placements, date windows, and filter predicates.
- Modify: `src/types/marketing.ts`
  - Adds fields needed for trustworthy creative/ad/campaign joins and media state.
- Modify: `src/components/Dashboard.tsx`
  - Uses pure analytics helpers and improves UI behavior for filters, creative ranking, media previews, and chat state.
- Modify: `backend/analysis_engine.py`
  - Ensures Meta ad rows are enriched with campaign/adset attribution and deduped recommendation rows.
- Modify: `backend/app.py`
  - Ensures dashboard mapping passes attribution and media fields through consistently.
- Create: `src/lib/analytics.test.ts`
  - Tests date windows, campaign filtering, creative ranking, and empty-state prevention.
- Create: `backend/test_analysis_engine.py`
  - Tests backend Meta enrichment and deduplication.

---

### Task 1: Add Frontend Analytics Tests

**Files:**

- Create: `src/lib/analytics.test.ts`
- Modify: `package.json`

- [ ] **Step 1: Add Vitest**

Run:

```powershell
npm install -D vitest jsdom @testing-library/react @testing-library/jest-dom
```

Expected: `package-lock.json` updates and install exits with code `0`.

- [ ] **Step 2: Add test scripts**

In `package.json`, add:

```json
{
  "scripts": {
    "test": "vitest run",
    "test:watch": "vitest"
  }
}
```

Keep existing scripts. Do not remove `dev`, `build`, `lint`, or `preview`.

- [ ] **Step 3: Export pure helpers from analytics**

In `src/lib/analytics.ts`, export helpers that are currently embedded in `Dashboard.tsx`:

```ts
export type DateRange = '7d' | '30d' | '90d'

export function getDateWindow(range: DateRange, anchorDate: string) {
  const days = range === '7d' ? 7 : range === '30d' ? 30 : 90
  const date = new Date(`${anchorDate}T00:00:00`)
  date.setDate(date.getDate() - days + 1)
  return { start: date.toISOString().slice(0, 10), end: anchorDate }
}

export function campaignOverlapsWindow(
  campaign: Pick<Campaign, 'startedAt' | 'endedAt' | 'status'>,
  window: { start: string; end: string },
) {
  const campaignStart = campaign.startedAt || window.start
  const campaignEnd = campaign.endedAt || (campaign.status === 'active' ? window.end : campaignStart)
  return campaignStart <= window.end && campaignEnd >= window.start
}
```

- [ ] **Step 4: Write failing analytics tests**

Create `src/lib/analytics.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { campaignOverlapsWindow, deriveCreativeScores, getDateWindow } from './analytics'
import type { Campaign, Creative, CreativeAnalysis, DailyAdMetric } from '../types/marketing'

describe('getDateWindow', () => {
  it('builds an inclusive 30 day window anchored to the latest dashboard date', () => {
    expect(getDateWindow('30d', '2026-05-28')).toEqual({
      start: '2026-04-29',
      end: '2026-05-28',
    })
  })
})

describe('campaignOverlapsWindow', () => {
  const window = { start: '2026-04-29', end: '2026-05-28' }

  it('excludes campaigns that ended before the selected window', () => {
    const campaign: Campaign = {
      id: 'old',
      platform: 'meta',
      name: 'Old campaign',
      objective: 'leads',
      status: 'completed',
      dailyBudgetUsd: 10,
      startedAt: '2026-03-01',
      endedAt: '2026-03-20',
    }

    expect(campaignOverlapsWindow(campaign, window)).toBe(false)
  })

  it('includes active campaigns that started inside the selected window', () => {
    const campaign: Campaign = {
      id: 'active',
      platform: 'meta',
      name: 'Active campaign',
      objective: 'leads',
      status: 'active',
      dailyBudgetUsd: 10,
      startedAt: '2026-05-10',
    }

    expect(campaignOverlapsWindow(campaign, window)).toBe(true)
  })
})

describe('deriveCreativeScores', () => {
  const creatives: Creative[] = [
    {
      id: 'creative_a',
      adId: 'ad_a',
      name: 'Buyer proof',
      format: 'video',
      theme: 'proof',
      hookType: 'case study',
      primaryPersona: 'business owner',
      cta: 'Join webinar',
    },
    {
      id: 'creative_b',
      adId: 'ad_b',
      name: 'Viral curiosity',
      format: 'video',
      theme: 'viral',
      hookType: 'curiosity',
      primaryPersona: 'broad',
      cta: 'Watch',
    },
  ]

  const analyses: CreativeAnalysis[] = [
    {
      creativeId: 'creative_a',
      viralScore: 55,
      buyerIntentScore: 88,
      courseFitScore: 90,
      purchasingPowerScore: 86,
      funnelQualityScore: 84,
      hookSummary: 'Specific business proof',
      conversionRisk: 'low',
      recommendedAction: 'Scale',
      sceneNotes: [],
      whyItWorked: 'It qualifies buyers.',
      whyItDidNotConvert: 'No major issue.',
    },
    {
      creativeId: 'creative_b',
      viralScore: 98,
      buyerIntentScore: 25,
      courseFitScore: 30,
      purchasingPowerScore: 20,
      funnelQualityScore: 18,
      hookSummary: 'Curiosity hook',
      conversionRisk: 'high',
      recommendedAction: 'Rebuild',
      sceneNotes: [],
      whyItWorked: 'It gets clicks.',
      whyItDidNotConvert: 'Weak purchase intent.',
    },
  ]

  const metrics: DailyAdMetric[] = [
    {
      date: '2026-05-20',
      campaignId: 'campaign_1',
      adSetId: 'adset_1',
      adId: 'ad_a',
      creativeId: 'creative_a',
      placement: 'instagram_reels',
      spendUsd: 100,
      impressions: 10000,
      clicks: 500,
      landingPageViews: 420,
      leads: 120,
      telegramSubscribers: 80,
      webinarAttendees: 30,
      purchases: 6,
      purchaseRevenueUsd: 1200,
    },
    {
      date: '2026-05-20',
      campaignId: 'campaign_1',
      adSetId: 'adset_2',
      adId: 'ad_b',
      creativeId: 'creative_b',
      placement: 'instagram_reels',
      spendUsd: 100,
      impressions: 30000,
      clicks: 2000,
      landingPageViews: 1200,
      leads: 220,
      telegramSubscribers: 40,
      webinarAttendees: 4,
      purchases: 0,
      purchaseRevenueUsd: 0,
    },
  ]

  it('ranks buyer-quality creatives above viral low-intent creatives', () => {
    const scores = deriveCreativeScores(metrics, creatives, analyses)

    expect(scores[0].id).toBe('creative_a')
    expect(scores[0].rank).toBe(1)
    expect(scores[1].id).toBe('creative_b')
    expect(scores[1].rank).toBe(2)
  })
})
```

- [ ] **Step 5: Run tests and verify they fail or pass meaningfully**

Run:

```powershell
npm test -- --run src/lib/analytics.test.ts
```

Expected after helper export: all tests pass.

- [ ] **Step 6: Commit Task 1**

Run:

```powershell
git add package.json package-lock.json src/lib/analytics.ts src/lib/analytics.test.ts
git commit -m "test: add dashboard analytics coverage"
```

---

### Task 2: Move Filtering Logic Into Tested Helpers

**Files:**

- Modify: `src/lib/analytics.ts`
- Modify: `src/components/Dashboard.tsx`
- Modify: `src/lib/analytics.test.ts`

- [ ] **Step 1: Add filter helpers to analytics**

Add to `src/lib/analytics.ts`:

```ts
export function filterMetricsForDashboard(args: {
  metrics: DailyAdMetric[]
  campaigns: Campaign[]
  ads: Ad[]
  creatives: Creative[]
  filters: {
    start: string
    campaignIds: string[]
    creativeFormat: 'all' | Creative['format']
    placement: 'all' | Placement
    objective: 'all' | Campaign['objective']
  }
}) {
  const campaignById = new Map(args.campaigns.map((campaign) => [campaign.id, campaign]))
  const adIds = new Set(args.ads.map((ad) => ad.id))
  const creativeById = new Map(args.creatives.map((creative) => [creative.id, creative]))

  return args.metrics.filter((metric) => {
    const creative = creativeById.get(metric.creativeId)
    const campaign = campaignById.get(metric.campaignId)

    return (
      metric.date >= args.filters.start &&
      (args.filters.campaignIds.includes('all') || args.filters.campaignIds.includes(metric.campaignId)) &&
      (args.filters.creativeFormat === 'all' || creative?.format === args.filters.creativeFormat) &&
      (args.filters.placement === 'all' || metric.placement === args.filters.placement) &&
      (args.filters.objective === 'all' || campaign?.objective === args.filters.objective) &&
      adIds.has(metric.adId)
    )
  })
}

export function getCampaignOptions(args: {
  campaigns: Campaign[]
  window: { start: string; end: string }
  objective: 'all' | Campaign['objective']
}) {
  return args.campaigns.filter(
    (campaign) =>
      campaignOverlapsWindow(campaign, args.window) &&
      (args.objective === 'all' || campaign.objective === args.objective),
  )
}
```

- [ ] **Step 2: Add tests for campaign option filtering**

Append to `src/lib/analytics.test.ts`:

```ts
import { filterMetricsForDashboard, getCampaignOptions } from './analytics'

describe('dashboard filtering', () => {
  it('only offers campaigns that overlap the selected date window', () => {
    const campaigns: Campaign[] = [
      {
        id: 'recent',
        platform: 'meta',
        name: 'Recent',
        objective: 'leads',
        status: 'active',
        dailyBudgetUsd: 20,
        startedAt: '2026-05-10',
      },
      {
        id: 'old',
        platform: 'meta',
        name: 'Old',
        objective: 'leads',
        status: 'completed',
        dailyBudgetUsd: 20,
        startedAt: '2026-02-01',
        endedAt: '2026-02-20',
      },
    ]

    expect(getCampaignOptions({
      campaigns,
      window: { start: '2026-04-29', end: '2026-05-28' },
      objective: 'all',
    }).map((campaign) => campaign.id)).toEqual(['recent'])
  })
})
```

- [ ] **Step 3: Use the helpers from Dashboard**

In `src/components/Dashboard.tsx`, update the analytics import:

```ts
import {
  deriveCreativeScores,
  deriveFunnel,
  derivePlacementScores,
  deriveTrend,
  filterMetricsForDashboard,
  formatNumber,
  getCampaignOptions,
  getDateWindow,
} from '../lib/analytics'
```

Replace local `filterMetrics`, `getCampaignOptionsForFilters`, and `getDateWindow` usage so the component calls the tested helpers.

- [ ] **Step 4: Remove duplicate local helper implementations**

Delete local functions in `Dashboard.tsx` when they are replaced:

```ts
function filterMetrics(...)
function getCampaignOptionsForFilters(...)
function getDateWindow(...)
```

Keep `getDashboardAnchorDate`, `labelPlacement`, `shortCampaignLabel`, and formatting helpers in `Dashboard.tsx` unless moving them is necessary.

- [ ] **Step 5: Verify tests and build**

Run:

```powershell
npm test -- --run src/lib/analytics.test.ts
npm run build
```

Expected: tests and TypeScript build pass.

- [ ] **Step 6: Commit Task 2**

Run:

```powershell
git add src/lib/analytics.ts src/components/Dashboard.tsx src/lib/analytics.test.ts
git commit -m "fix: make dashboard filters deterministic"
```

---

### Task 3: Fix Backend Meta Attribution for Creatives

**Files:**

- Modify: `backend/analysis_engine.py`
- Modify: `backend/app.py`
- Create: `backend/test_analysis_engine.py`

- [ ] **Step 1: Add backend test dependencies if needed**

Run:

```powershell
python -m pip install pytest
```

Expected: pytest is available.

- [ ] **Step 2: Write attribution test**

Create `backend/test_analysis_engine.py`:

```python
from backend.app import map_creative, map_metric


def test_map_creative_preserves_meta_attribution_and_media():
    row = {
        "id": "ad_1",
        "campaign_id": "campaign_1",
        "adset_id": "adset_1",
        "name": "VID - 08",
        "creative": {
            "id": "creative_meta_1",
            "name": "Creative 1",
            "title": "Proof hook",
            "thumbnail_url": "https://example.com/thumb.jpg",
            "video_id": "video_1",
            "video_url": "https://example.com/video.mp4",
        },
    }

    creative = map_creative(row)

    assert creative["id"] == "creative_meta_1"
    assert creative["adId"] == "ad_1"
    assert creative["campaignId"] == "campaign_1"
    assert creative["adSetId"] == "adset_1"
    assert creative["assetUrl"] == "https://example.com/thumb.jpg"
    assert creative["videoId"] == "video_1"
    assert creative["videoUrl"] == "https://example.com/video.mp4"


def test_map_metric_uses_meta_creative_id_when_available():
    row = {
        "date_start": "2026-05-20",
        "campaign_id": "campaign_1",
        "adset_id": "adset_1",
        "ad_id": "ad_1",
        "creative_id": "creative_meta_1",
        "publisher_platform": "instagram",
        "platform_position": "reels",
        "spend": "10",
        "impressions": "1000",
        "clicks": "100",
        "actions": [{"action_type": "lead", "value": "7"}],
    }

    metric = map_metric(row)

    assert metric["campaignId"] == "campaign_1"
    assert metric["adSetId"] == "adset_1"
    assert metric["adId"] == "ad_1"
    assert metric["creativeId"] == "creative_meta_1"
```

- [ ] **Step 3: Run test to expose missing fields**

Run:

```powershell
python -m pytest backend/test_analysis_engine.py -v
```

Expected before implementation: at least one assertion fails if `campaignId`, `adSetId`, or real creative ID are missing.

- [ ] **Step 4: Update frontend types for attribution on creatives**

In `src/types/marketing.ts`, extend `Creative`:

```ts
export interface Creative {
  id: string
  adId: string
  campaignId?: string
  adSetId?: string
  name: string
  format: 'video' | 'image' | 'gif' | 'carousel'
  theme: string
  hookType: string
  primaryPersona: string
  cta: string
  assetUrl?: string
  videoId?: string
  videoUrl?: string
}
```

- [ ] **Step 5: Update backend creative ID mapping**

In `backend/app.py`, change `creative_id_for_ad` to accept a real creative ID:

```python
def creative_id_for_ad(ad_id: Any, creative_id: Any = None) -> str:
    if creative_id:
        return str(creative_id)
    return f"creative_{ad_id}"
```

Update `map_creative(row)` to use:

```python
creative_id = creative_id_for_ad(row.get("id"), creative.get("id"))
```

Return these fields:

```python
"campaignId": str(row.get("campaign_id") or ""),
"adSetId": str(row.get("adset_id") or ""),
"videoUrl": creative.get("video_url"),
```

- [ ] **Step 6: Update backend metric mapping**

In `backend/app.py`, update `map_metric(row)` so `creativeId` prefers a `creative_id` from enriched insight rows:

```python
creative_id = row.get("creative_id") or row.get("creative", {}).get("id")
...
"creativeId": creative_id_for_ad(ad_id, creative_id),
```

- [ ] **Step 7: Enrich insight rows with ad creative IDs**

In the backend path that joins raw ads and insights before `map_metric`, add a lookup:

```python
ad_lookup = {str(ad.get("id")): ad for ad in raw_ads}
for row in raw_metrics:
    ad = ad_lookup.get(str(row.get("ad_id")))
    if ad:
        creative = ad.get("creative") or {}
        row["creative_id"] = creative.get("id") or row.get("creative_id")
```

- [ ] **Step 8: Verify backend tests**

Run:

```powershell
python -m pytest backend/test_analysis_engine.py -v
```

Expected: both tests pass.

- [ ] **Step 9: Verify frontend build still passes**

Run:

```powershell
npm run build
```

Expected: TypeScript build passes.

- [ ] **Step 10: Commit Task 3**

Run:

```powershell
git add backend/app.py backend/analysis_engine.py backend/test_analysis_engine.py src/types/marketing.ts
git commit -m "fix: preserve creative attribution from Meta"
```

---

### Task 4: Make Creative Media Display Honest

**Files:**

- Modify: `src/components/Dashboard.tsx`
- Modify: `src/App.css`

- [ ] **Step 1: Update MediaThumb rules**

Find `MediaThumb` in `src/components/Dashboard.tsx`. Make its rule explicit:

```tsx
function MediaThumb({
  assetUrl,
  videoUrl,
  videoId,
  format,
}: {
  assetUrl?: string
  videoUrl?: string
  videoId?: string
  format: Creative['format']
}) {
  const hasPlayableVideo = Boolean(videoUrl)

  return (
    <div className={`creative-thumb ${assetUrl ? 'has-image' : ''}`}>
      {assetUrl ? <img src={assetUrl} alt="" loading="lazy" /> : <Film size={18} />}
      {hasPlayableVideo && <i aria-label="Playable video">▶</i>}
      {!hasPlayableVideo && videoId && <span title="Video ID exists, but source URL is unavailable">ID</span>}
      {!assetUrl && <small>{format}</small>}
    </div>
  )
}
```

- [ ] **Step 2: Update selected creative preview**

Find the creative detail preview in `CreativesView`. Use:

```tsx
{selectedCreative.videoUrl ? (
  <video src={selectedCreative.videoUrl} controls poster={selectedCreative.assetUrl} />
) : selectedCreative.assetUrl ? (
  <img src={selectedCreative.assetUrl} alt={selectedCreative.name} />
) : (
  <div>
    <Film size={24} />
    <strong>No media preview available</strong>
    <span>Meta returned metadata but no playable source URL.</span>
  </div>
)}
```

- [ ] **Step 3: Add CSS for non-playable video ID state**

In `src/App.css`, add:

```css
.creative-thumb span {
  position: absolute;
  right: 4px;
  bottom: 4px;
  padding: 2px 4px;
  border-radius: 4px;
  background: rgba(15, 23, 42, 0.8);
  color: #fff;
  font-size: 0.65rem;
  font-weight: 700;
}
```

- [ ] **Step 4: Verify build**

Run:

```powershell
npm run build
```

Expected: build passes.

- [ ] **Step 5: Commit Task 4**

Run:

```powershell
git add src/components/Dashboard.tsx src/App.css
git commit -m "fix: show creative media availability accurately"
```

---

### Task 5: Add First-Pass Rankings Hub

**Files:**

- Modify: `src/lib/analytics.ts`
- Modify: `src/components/Dashboard.tsx`
- Modify: `src/types/marketing.ts`
- Modify: `src/App.css`
- Modify: `src/lib/analytics.test.ts`

- [ ] **Step 1: Add ranking types**

In `src/types/marketing.ts`, add:

```ts
export interface RankingRow {
  id: string
  rank: number
  name: string
  category: 'segment' | 'campaign' | 'audience' | 'creative' | 'placement'
  spendUsd: number
  clicks: number
  leads: number
  telegramSubscribers: number
  purchases: number
  cpl: number
  costPerTelegramStart: number
  buyerRate: number
  qualityScore: number
  recommendedAction: string
  tone: Tone
}
```

- [ ] **Step 2: Add generic ranking helper**

In `src/lib/analytics.ts`, add:

```ts
export function deriveRankingRows(
  metrics: DailyAdMetric[],
  groups: Array<{ id: string; name: string; category: RankingRow['category']; metricIds: Set<string> }>,
): RankingRow[] {
  return groups
    .map((group) => {
      const rows = metrics.filter((metric) => group.metricIds.has(metric.adId) || group.metricIds.has(metric.creativeId) || group.metricIds.has(metric.campaignId) || group.metricIds.has(metric.adSetId) || group.metricIds.has(metric.placement))
      const spendUsd = sumBy(rows, (row) => row.spendUsd)
      const clicks = sumBy(rows, (row) => row.clicks)
      const leads = sumBy(rows, (row) => row.leads)
      const telegramSubscribers = sumBy(rows, (row) => row.telegramSubscribers)
      const purchases = sumBy(rows, (row) => row.purchases)
      const cpl = leads === 0 ? 0 : spendUsd / leads
      const costPerTelegramStart = telegramSubscribers === 0 ? 0 : spendUsd / telegramSubscribers
      const buyerRate = leads === 0 ? 0 : purchases / leads
      const qualityScore = Math.round(
        Math.min(45, buyerRate * 1000) +
          Math.min(35, telegramSubscribers === 0 ? 0 : (telegramSubscribers / Math.max(1, clicks)) * 100) +
          Math.min(20, clicks === 0 ? 0 : (leads / clicks) * 50),
      )
      const tone: Tone = qualityScore >= 70 ? 'good' : qualityScore >= 40 ? 'warning' : 'danger'
      const recommendedAction =
        purchases > 0 || qualityScore >= 70 ? 'Scale carefully' : clicks > 0 && telegramSubscribers === 0 ? 'Audit funnel' : 'Review'

      return {
        id: group.id,
        rank: 0,
        name: group.name,
        category: group.category,
        spendUsd,
        clicks,
        leads,
        telegramSubscribers,
        purchases,
        cpl,
        costPerTelegramStart,
        buyerRate,
        qualityScore,
        recommendedAction,
        tone,
      }
    })
    .filter((row) => row.spendUsd > 0 || row.clicks > 0 || row.leads > 0)
    .sort((a, b) => b.qualityScore - a.qualityScore || b.purchases - a.purchases || b.telegramSubscribers - a.telegramSubscribers)
    .map((row, index) => ({ ...row, rank: index + 1 }))
}
```

- [ ] **Step 3: Add ranking tests**

Append to `src/lib/analytics.test.ts`:

```ts
import { deriveRankingRows } from './analytics'

describe('deriveRankingRows', () => {
  it('ranks groups by quality instead of raw clicks', () => {
    const rows = deriveRankingRows(
      [
        {
          date: '2026-05-20',
          campaignId: 'campaign_quality',
          adSetId: 'adset_1',
          adId: 'ad_1',
          creativeId: 'creative_1',
          placement: 'instagram_reels',
          spendUsd: 100,
          impressions: 1000,
          clicks: 100,
          landingPageViews: 80,
          leads: 40,
          telegramSubscribers: 30,
          webinarAttendees: 0,
          purchases: 4,
          purchaseRevenueUsd: 1000,
        },
        {
          date: '2026-05-20',
          campaignId: 'campaign_clicks',
          adSetId: 'adset_2',
          adId: 'ad_2',
          creativeId: 'creative_2',
          placement: 'instagram_reels',
          spendUsd: 100,
          impressions: 10000,
          clicks: 900,
          landingPageViews: 600,
          leads: 100,
          telegramSubscribers: 5,
          webinarAttendees: 0,
          purchases: 0,
          purchaseRevenueUsd: 0,
        },
      ],
      [
        { id: 'campaign_quality', name: 'Quality', category: 'campaign', metricIds: new Set(['campaign_quality']) },
        { id: 'campaign_clicks', name: 'Clicks', category: 'campaign', metricIds: new Set(['campaign_clicks']) },
      ],
    )

    expect(rows[0].id).toBe('campaign_quality')
    expect(rows[0].rank).toBe(1)
  })
})
```

- [ ] **Step 4: Add rankings view**

In `src/components/Dashboard.tsx`, add a nav item:

```ts
{ id: 'rankings', label: 'Rankings', icon: BarChart3 },
```

Add a `RankingsView` that shows tabs/cards for:

- Campaigns
- Creatives
- Audiences/ad sets
- Placements

Use quality-adjusted ranking as the default.

- [ ] **Step 5: Verify tests and build**

Run:

```powershell
npm test -- --run src/lib/analytics.test.ts
npm run build
```

Expected: tests and build pass.

- [ ] **Step 6: Commit Task 5**

Run:

```powershell
git add src/lib/analytics.ts src/components/Dashboard.tsx src/types/marketing.ts src/App.css src/lib/analytics.test.ts
git commit -m "feat: add dashboard rankings hub"
```

---

### Task 6: Fix Chat and Refresh Loading States

**Files:**

- Modify: `src/components/Dashboard.tsx`
- Modify: `src/services/agentChatProvider.ts`
- Modify: `backend/app.py`

- [ ] **Step 1: Add request IDs to chat messages**

In `src/components/Dashboard.tsx`, update `ChatMessage`:

```ts
interface ChatMessage {
  id: string
  role: 'user' | 'agent'
  content: string
  sources?: string[]
  suggestedQuestions?: string[]
}
```

Add helper:

```ts
function makeMessageId() {
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`
}
```

- [ ] **Step 2: Use stable IDs in chat rendering**

Update initial chat message:

```ts
{
  id: 'initial-agent-message',
  role: 'agent',
  content: 'Ask me about creatives, placements, audiences, funnel leaks, experiments, or Meta connection status.',
  sources: ['agent'],
}
```

Update message rendering:

```tsx
{messages.map((message) => (
  <div className={`chat-message ${message.role}`} key={message.id}>
```

- [ ] **Step 3: Keep response attached to the latest request**

In `sendChatMessage`, create IDs before state updates:

```ts
const userMessageId = makeMessageId()
const agentMessageId = makeMessageId()
```

Add the user message and then append the agent message only for that request. Keep `isChatLoading` disabled during in-flight requests so a suggestion cannot accidentally send a second question before the first answer returns.

- [ ] **Step 4: Add backend timeout-safe chat response**

In `backend/app.py`, ensure `agent_chat` catches LLM errors and always returns the deterministic fallback:

```python
try:
    llm_answer = await generate_chat_answer(question, knowledge_chat_preview(knowledge))
except Exception:
    llm_answer = None
```

- [ ] **Step 5: Verify build and manual chat behavior**

Run:

```powershell
npm run build
```

Then run backend and frontend:

```powershell
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
npm run dev -- --host 127.0.0.1 --port 5173
```

Manual check:

- Send "Which creative should we scale?"
- Click one suggested question.
- Confirm one user message gets one relevant agent answer.
- Confirm send button disables while thinking.

- [ ] **Step 6: Commit Task 6**

Run:

```powershell
git add src/components/Dashboard.tsx src/services/agentChatProvider.ts backend/app.py
git commit -m "fix: stabilize agent chat requests"
```

---

### Task 7: Add Dashboard Verification Checklist

**Files:**

- Create: `docs/QA_CHECKLIST.md`
- Modify: `README.md`

- [ ] **Step 1: Create QA checklist**

Create `docs/QA_CHECKLIST.md`:

```md
# Dashboard QA Checklist

Run this before pushing dashboard changes.

## Commands

- `npm test`
- `npm run build`
- `python -m pytest backend/test_analysis_engine.py -v`

## Manual Checks

- 7/30/90 day filter only shows campaigns active inside that window.
- Multi-campaign selection updates all KPIs, charts, funnel, placements, and creative rankings.
- A campaign with no metric rows shows a clear empty state and a reset button.
- Creative table is ranked by quality score and starts at rank 1.
- Creative thumbnails render when available.
- A play marker appears only when `videoUrl` exists.
- Agent chat gives one answer per question and shows sources.
- Meta connection status never exposes access tokens.
```

- [ ] **Step 2: Link checklist from README**

Add to `README.md`:

```md
## Quality Checks

Before pushing a dashboard change, run the checklist in `docs/QA_CHECKLIST.md`.
```

- [ ] **Step 3: Run checks**

Run:

```powershell
npm test
npm run build
python -m pytest backend/test_analysis_engine.py -v
```

Expected: all checks pass.

- [ ] **Step 4: Commit Task 7**

Run:

```powershell
git add docs/QA_CHECKLIST.md README.md
git commit -m "docs: add dashboard QA checklist"
```

---

## Plan Self-Review

Spec coverage:

- Version 0.2 dashboard filtering: covered by Tasks 1-2.
- Multi-campaign selection reliability: covered by Task 2.
- Creative-to-campaign mapping: covered by Task 3.
- Creative ranking: covered by Task 1 and existing `deriveCreativeScores`.
- Thumbnail/video honesty: covered by Task 4.
- Rankings hub: covered by Task 5.
- Chat request state: covered by Task 6.
- Verification before GitHub push: covered by Task 7.

Known follow-up after this plan:

- Version 0.3 should add reliable Meta read-only import with persisted snapshots.
- Version 0.4 should add the three-segment landing/Telegram event API.
- Version 0.5 should add CRM Google Sheet import and stage mapping.
