# Meta Ads Audit Agent Architecture and Version Roadmap

Date: 2026-05-28

## 1. Goal

Build a Meta Ads audit, strategy, monitoring, and execution agent for online AI course campaigns.

The system must learn from historical Meta ad performance, understand creative and audience quality, monitor active campaigns, explain why metrics are improving or getting worse, and recommend controlled experiments. Over time, after human approval, it should be able to create or adjust campaigns in Meta Ads and then monitor the result.

The agent should optimize for two layers of success:

1. Short-term signal: high-quality Telegram bot subscribers and CRM form submissions.
2. True business signal: paid course purchases, partial payments, full payments, and revenue.

## 2. Campaign Structure

The campaign structure must be configurable. A campaign playbook can use one VSL, three VSLs, five VSLs, or any other number that the user defines.

Each playbook segment should be user-configurable:

- Segment name
- Segment description
- VSL name/ID
- Landing page URL
- Telegram bot URL
- Target audience notes
- Pain points
- Primary offer angle
- Creative count target
- Starting budget
- Success metric override
- Segment-specific guardrails

The next campaign will use three separate funnel segments as the first example playbook.

| Segment | VSL Theme | Funnel |
| --- | --- | --- |
| income | Earning money / income | Meta ads -> income landing page -> income Telegram bot -> Bitrix24 form |
| business_automation | Productivity, automation, AI agents for businesses | Meta ads -> business landing page -> business Telegram bot -> Bitrix24 form |
| content_creators | Content creators and video editors | Meta ads -> creator landing page -> creator Telegram bot -> Bitrix24 form |

For the first example playbook, each segment will have approximately 8-10 creative videos. Future playbooks may use any number of creatives per segment. The agent must compare performance at both levels:

- Segment level: which funnel theme produces the best lead quality and buyer quality.
- Creative level: which individual video attracts the best audience inside each segment.

### 2.1 Configurable Campaign Playbooks

The system must not hardcode one campaign structure, one budget, or one success metric. Each new launch should be configured through a campaign playbook.

Campaign playbook variables:

- Campaign name
- Campaign goal
- Number of segments/VSLs
- Segment definitions
- Target audience definitions per segment
- Pain points per segment
- Offer/message angle per segment
- Landing page URLs
- Telegram bot URLs
- Starting budget per segment
- Maximum daily budget
- Maximum total budget
- Scaling step percentage
- Scaling frequency
- Primary success metric
- Secondary success metrics
- Sales capacity limit
- Alert channels
- Approval channels
- Kill rules
- Scale rules
- Experiment duration

The current three-VSL launch is the first playbook, not a permanent system assumption.

Initial example playbook:

- Income VSL: $100/day
- Business automation VSL: $100/day
- Content creator/video editor VSL: $100/day
- Scaling step: up to 20%
- Scaling frequency: daily or every 2 days
- Primary early success metric: Telegram bot START

Future campaign example:

- Segment count can be 1, 2, 3, 4, or more.
- The user can input different target audiences and segmentation logic for each new campaign.
- Starting budget can be $200/day or another value.
- Primary success metric can change from Telegram START to CRM qualified lead, buyer, revenue, or another configured metric.

Primary early success metric:

- For the current first playbook, qualified lead = a person who clicks `START` in the Telegram bot and enters the funnel with preserved attribution.
- For future playbooks, the user can choose a different primary success metric.

Later success metrics:

- CRM form submission
- qualified CRM lead
- high-intent CRM stage
- partial buyer
- full buyer
- revenue

General scaling rule:

- Do not increase budget only because CPL is cheap.
- Require the configured primary success metric and guardrail metrics before scaling.
- If sales lead volume exceeds the configured sales-team capacity, do not scale until quality improves or capacity increases.
- Never execute budget changes without approval.

## 3. Source Systems

### 3.1 Meta Marketing API

Read data from the connected Meta ad account:

- Campaigns
- Ad sets
- Ads
- Creatives
- Insights
- Breakdowns by age, gender, placement, region/city, and platform where available
- Pixel events where available

Initial mode must be read-only. Write actions must be locked behind explicit user approval.

### 3.2 Landing Pages

There will be three landing pages, one per segment. Each landing page must capture and forward attribution data:

- `visitor_id`
- `segment`
- `vsl_id`
- `landing_page_id`
- `campaign_id`
- `adset_id`
- `ad_id`
- `creative_id`
- `utm_source`
- `utm_medium`
- `utm_campaign`
- `utm_content`
- `utm_term`
- `fbclid`

Landing page events:

- `landing_view`
- `vsl_button_click`
- `telegram_link_click`

### 3.3 Telegram Bots via ChatPlace

The three Telegram bots will be built manually in ChatPlace. ChatPlace will send event data to our backend through External API Request blocks.

Required events:

- `bot_start`
- `vsl_sequence_started`
- `vsl_key_message_sent`
- `form_button_click`
- `form_opened`

Recommended rule: use ChatPlace delay settings carefully so the 20-minute message is not interrupted by another automation. The bot builder should enable the setting that keeps the delay working without interruption when needed.

### 3.4 Bitrix24 CRM Form

The CRM form is hosted on Bitrix24 and controlled by the outsourced sales team. The form must be configured to save hidden fields or URL parameters into each lead/deal record.

Required hidden/custom fields:

- `segment`
- `vsl_id`
- `landing_page_id`
- `telegram_bot_id`
- `campaign_id`
- `adset_id`
- `ad_id`
- `creative_id`
- `telegram_user_id`
- `visitor_id`
- `utm_source`
- `utm_medium`
- `utm_campaign`
- `utm_content`
- `utm_term`
- `fbclid`

The outsourced sales team should confirm that these values appear in the CRM lead/deal record after a test submission.

### 3.5 CRM Google Sheet Import

Version 1 will use manual Google Sheet or CSV import from the outsourced sales team.

The sales pipeline stages are not fixed yet, so the system must support flexible stage mapping.

Expected columns:

- `created_at`
- `lead_id`
- `phone_or_user_id`
- `raw_stage`
- `status_notes`
- `payment_amount`
- `segment`
- `vsl_id`
- `campaign_id`
- `adset_id`
- `ad_id`
- `creative_id`
- `telegram_user_id`
- `visitor_id`
- `utm_source`
- `utm_medium`
- `utm_campaign`
- `utm_content`
- `fbclid`
- `salesperson`
- `lost_reason`

The dashboard must let the user map raw CRM stages into normalized agent stages:

- `early_lead`
- `qualified_lead`
- `high_intent`
- `partial_buyer`
- `full_buyer`
- `disqualified`
- `unknown`

## 4. Attribution Model

Every user journey should preserve attribution from ad click to payment.

Recommended flow:

```text
Meta ad click
-> landing page visitor_id created
-> Telegram deep link includes visitor_id and segment
-> ChatPlace bot sends visitor and Telegram events to backend
-> Bitrix24 form URL includes visitor_id and attribution fields
-> Google Sheet or API export returns CRM stage and payment data
-> Agent joins CRM outcome back to campaign, ad set, ad, creative, segment, and VSL
```

Example Bitrix24 form URL:

```text
https://inafform.bitrix24.site/crm_form_vospb/
?segment=income
&vsl_id=income_vsl_01
&landing_page_id=income_lp_01
&telegram_bot_id=income_bot
&campaign_id={{campaign_id}}
&adset_id={{adset_id}}
&ad_id={{ad_id}}
&creative_id={{creative_id}}
&telegram_user_id={{telegram_user_id}}
&visitor_id={{visitor_id}}
&utm_source=meta
&utm_medium=paid
&utm_campaign={{campaign_name}}
&utm_content={{creative_id}}
&utm_term={{interest_or_adset}}
&fbclid={{fbclid}}
```

## 5. Core Metrics

### 5.1 Meta Metrics

- Spend
- Impressions
- Reach
- Frequency
- CPM
- Link clicks
- CTR
- CPC
- Landing page views
- Cost per landing page view
- Meta leads or registrations
- Cost per Meta lead

### 5.2 Landing Page Metrics

- Landing visit rate = landing views / Meta clicks
- VSL button click rate = VSL button clicks / landing views
- Telegram link click rate = Telegram link clicks / landing views
- Landing page leak rate = 1 - VSL button click rate

### 5.3 Telegram Metrics

- Bot start rate = bot starts / Telegram link clicks
- 20-minute message reach rate = key messages sent / bot starts
- Form button click rate = form button clicks / key messages sent
- Cost per bot start
- Cost per form button click

### 5.4 CRM and Revenue Metrics

- Form submit rate = CRM form submissions / form button clicks
- Qualified lead rate = qualified leads / form submissions
- High-intent rate = high-intent leads / form submissions
- Partial buyer rate = partial buyers / form submissions
- Full buyer rate = full buyers / form submissions
- Cost per qualified lead
- Cost per high-intent lead
- Cost per partial buyer
- Cost per full buyer
- Revenue
- ROAS
- Profit estimate where cost and revenue are available

## 6. Lead Quality Score

The agent should not optimize only for cheap clicks or cheap leads. It should calculate a weighted quality score.

Initial scoring model:

| Event / stage | Points |
| --- | ---: |
| Landing page visit | 1 |
| Telegram bot start | 3 |
| 20-minute message reached | 4 |
| CRM form button click | 6 |
| CRM form submitted | 8 |
| Qualified lead | 12 |
| High intent | 20 |
| Partial buyer | 50 |
| Full buyer | 100 |
| Disqualified | -10 |

The quality score should be adjustable in dashboard settings.

## 7. Agent Responsibilities

### 7.1 Audit Agent

Reads historical data and explains:

- Which campaigns worked and why
- Which campaigns created cheap but low-quality traffic
- Which audiences converted cheaply
- Which audiences produced better CRM/payment quality
- Which placements should be scaled, tested, or reduced
- Which age/gender/location segments deserve more or less budget

### 7.2 Creative Intelligence Agent

Analyzes creative assets and ranks them by both performance and quality.

Responsibilities:

- Pull thumbnails and video metadata from Meta where allowed.
- Store creative files or references.
- Analyze each video with Gemini/OpenAI vision or extracted video frames.
- Classify hook type, promise, pain point, visual pattern, CTA clarity, buyer intent, and viral risk.
- Explain why top creatives worked and why some viral creatives failed to convert.

### 7.3 Funnel Tracking Agent

Tracks landing, Telegram, and CRM funnel events.

Responsibilities:

- Receive events from landing pages and ChatPlace.
- Import CRM Google Sheet or CSV.
- Join event data into one user journey where possible.
- Detect funnel leaks by segment, creative, and date.

### 7.4 Monitoring Agent

Runs every 4 hours during active campaigns.

Responsibilities:

- Compare current performance against expected targets.
- Detect rising CPL, rising CPC, falling CTR, funnel leaks, fatigue, or poor lead quality.
- Explain likely causes.
- Recommend top 2-3 actions.
- Send alerts to the dashboard and optionally Telegram/email.

### 7.5 Experiment Agent

Suggests controlled experiments.

Examples:

- Shift budget from low-quality income creatives to business automation creatives.
- Pause creatives with high CTR but poor Telegram/form quality.
- Test Instagram-only placements when Facebook quality is worse.
- Test narrower age groups if CRM quality proves stronger.
- Split business automation into business owners vs freelancers vs operators.

Initial 48-hour rules:

- Do not kill an ad set only because CPL is higher if Telegram start quality is strong.
- Flag a creative for review if it spends meaningfully and produces high clicks but weak Telegram starts.
- Flag a funnel mismatch if click and landing visit rates are healthy but Telegram starts are weak.
- Flag a sales capacity risk if projected daily form leads exceed 160-200 leads/day.
- Recommend scaling only when a segment or creative has both adequate volume and stronger quality than the account average.
- Recommend budget increases in 20% steps, not aggressive jumps.

### 7.6 Execution Agent

Later version only. Makes changes in Meta Ads after explicit approval.

Allowed actions after approval:

- Create draft campaigns
- Create ad sets
- Upload creatives
- Adjust budgets
- Pause underperforming ads or ad sets
- Change placements
- Duplicate winning ad sets

Blocked without approval:

- Increasing total budget
- Publishing new campaigns
- Pausing high-spend campaigns
- Changing payment or account settings
- Removing campaigns, ad sets, ads, or creatives

Approval channels:

- Dashboard approval queue
- Telegram approval bot with approve/reject buttons

Execution rule:

- The agent may analyze and recommend autonomously.
- The agent must ask for approval every time before executing a Meta Ads change.
- Every approved action must store the approving user, timestamp, reason, before/after settings, and execution result.

## 8. Dashboard Requirements

### 8.1 Main Dashboard

Show overall performance across all funnels:

- Spend
- Clicks
- Landing views
- Telegram bot starts
- CRM form submissions
- Qualified leads
- Buyers
- Revenue
- CPL
- Cost per bot start
- Cost per form submission
- Cost per buyer

### 8.2 Segment Comparison

Compare user-defined playbook segments. For the first example playbook, this means:

- Income
- Business automation
- Content creators

For future playbooks, this view must render whatever segments the user configured.

Charts:

- Spend by segment
- Cost per bot start by segment
- Cost per form submit by segment
- Quality score by segment
- Buyer rate by segment

### 8.3 Creative Library

Requirements:

- Show all creatives, not only the first 50.
- Show thumbnails where available.
- Show playable video when a video URL/source is available.
- Remove misleading play icons when only a thumbnail exists.
- Rank creatives by quality-adjusted performance, not raw clicks.
- Support filters by segment, campaign, ad set, creative theme, hook type, and date.

### 8.4 Campaign and Ad Set View

Show:

- Campaign status
- Objective
- Spend
- Budget
- CTR
- CPC
- CPM
- CPL
- Cost per bot start
- Cost per form submit
- Cost per buyer
- Placements
- Age/gender/location breakdown
- Interest/ad set performance
- Agent recommendation

### 8.5 Funnel View

Visualize the journey:

```text
Impressions -> Clicks -> Landing views -> VSL button clicks -> Bot starts -> 20-min reached -> Form clicks -> CRM leads -> Buyers
```

Must support filtering by segment, campaign, ad set, creative, and date range.

### 8.6 CRM Import View

Features:

- Upload CSV/XLSX.
- Preview rows.
- Map columns.
- Map raw stages to normalized stages.
- Show import errors.
- Store import history.
- Recalculate quality metrics after import.

### 8.7 Agent Chat

The chat should answer from the knowledge base and current dashboard data.

Example questions:

- Which segment should we scale?
- Which creatives attract cheap but weak leads?
- Which age and gender should we target?
- Which placements should we avoid?
- Why did CPL rise today?
- What are the top 3 experiments for tomorrow?
- Which campaign produced the best high-intent leads?

The chat must cite the data source used:

- Meta data
- Landing events
- Telegram events
- CRM import
- Creative analysis
- Agent knowledge base

### 8.8 Rankings Hub

The dashboard should provide ranking views for:

- Segments
- Campaigns
- Ad sets/audiences
- Creatives
- Placements
- Regions/cities

Ranking logic should support:

- cheapest raw lead
- best Telegram-start cost
- best qualified lead quality
- best buyer quality
- highest waste
- highest scale opportunity
- strongest proof/creative quality

The default ranking should be quality-adjusted, not raw lead volume.

## 9. Knowledge Base

The system should maintain a persistent knowledge base from historical data and manual observations.

Stored knowledge:

- Campaign summaries
- Lessons learned
- Winning audiences
- Losing audiences
- Winning creative themes
- Creative failure patterns
- Placement decisions
- Segment-level performance
- CRM quality findings
- Approved experiments
- Experiment outcomes

The agent should use this knowledge base when suggesting new campaigns.

## 10. Safety and Approval Model

The agent must be autonomous in monitoring and analysis, but controlled in execution.

Approval levels:

| Level | Agent can do | Approval needed |
| --- | --- | --- |
| L0 read-only | Fetch data, analyze, summarize | No |
| L1 alerts | Send warnings and recommendations | No |
| L2 draft actions | Prepare campaign/adset/ad changes as drafts | Yes before publish |
| L3 limited optimization | Pause or reduce budget within predefined rules | Yes initially |
| L4 autonomous optimization | Execute approved playbooks automatically | Future only |

Version 1 and Version 2 must stay in L0-L1 mode.

Current user preference:

- Recommendations can be autonomous and detailed.
- Execution must always require approval.
- Approvals should be possible from both the dashboard and Telegram bot.
- Telegram alerts should include approve/reject buttons for executable recommendations.
- Budget, success metrics, segments, scaling rules, and campaign goals must be configurable per campaign playbook.

## 11. Technical Architecture

Recommended local architecture:

```text
Frontend dashboard
  React/Vite or Next.js

Backend API
  FastAPI or Next.js API routes

Database
  PostgreSQL recommended for production
  SQLite acceptable for local prototype

Storage
  Local/R2/S3 for creative thumbnails, video snapshots, and analysis artifacts

Workers / scheduler
  4-hour monitoring jobs
  Meta import jobs
  CRM import jobs
  creative analysis jobs

LLM layer
  OpenAI/Gemini for analysis, chat, and creative/video understanding

Integrations
  Meta Marketing API
  Landing page event API
  ChatPlace external API requests
  Google Sheet/CSV import
  Bitrix24 API later
```

Recommended deployment architecture later:

```text
Web dashboard
-> Backend API
-> PostgreSQL
-> Background workers
-> Object storage
-> Scheduled monitor every 4 hours
-> Notification channel
```

## 12. Data Tables

### 12.1 Core Tables

- `accounts`
- `campaigns`
- `adsets`
- `ads`
- `creatives`
- `daily_insights`
- `breakdown_insights`
- `funnel_events`
- `crm_imports`
- `crm_leads`
- `stage_mappings`
- `creative_analyses`
- `knowledge_items`
- `recommendations`
- `experiments`
- `agent_runs`
- `approval_requests`

### 12.2 Important IDs

Every table that stores performance should preserve:

- `segment`
- `vsl_id`
- `campaign_id`
- `adset_id`
- `ad_id`
- `creative_id`
- `visitor_id`
- `telegram_user_id`
- `lead_id`

## 13. Version Roadmap

### Version 0.1: Specification and Git Foundation

Goal: create a professional project foundation.

Deliverables:

- Architecture/specification document.
- Version roadmap.
- Git repository structure.
- `.env.example` without secrets.
- README update.
- First GitHub push after review.

### Version 0.2: Data Cleanup and Current Dashboard Fixes

Goal: make the existing dashboard trustworthy.

Deliverables:

- Correct campaign/date filtering.
- Multi-campaign selection.
- Fix creative-to-campaign mapping.
- Rank creatives by performance and quality.
- Show thumbnails when available.
- Show playable videos only when video source is available.
- Fix refresh/loading state.
- Remove duplicate waste rows.
- Add clear empty-state explanations.

### Version 0.3: Meta Read-Only Import

Goal: reliably import Meta data for the last 90 days and then 6 months.

Deliverables:

- Meta API connection status.
- Campaign/ad set/ad/creative import.
- Insights import.
- Breakdowns by age, gender, placement, region/city where available.
- Store normalized snapshots.
- Dashboard source badge: mock, imported, live.

### Version 0.4: Three-Segment Funnel Tracking

Goal: track landing page and Telegram funnel events.

Deliverables:

- Event API endpoint.
- Visitor ID generation.
- Segment/VSL/landing/bot IDs.
- ChatPlace External API Request payload templates.
- Landing page URL parameter templates.
- Funnel dashboard by segment.

### Version 0.5: CRM Google Sheet Import

Goal: connect sales quality to ad performance.

Deliverables:

- CSV/XLSX upload.
- Column mapping.
- Stage mapping.
- Import validation.
- CRM lead table.
- Quality score recalculation.
- Segment and creative quality dashboards.

### Version 0.6: Knowledge Base and Agent Chat

Goal: make the agent answer accurately from data.

Deliverables:

- Knowledge base generation from Meta, funnel, CRM, and creative data.
- Chat retrieval from current data and knowledge base.
- Source citations in chat answers.
- Saved lessons learned.
- 90-day and 6-month audit reports.

### Version 0.7: Creative Intelligence

Goal: understand why creatives work or fail.

Deliverables:

- Creative thumbnail/video import.
- Video frame extraction if video files are available.
- Gemini/OpenAI visual analysis.
- Hook/theme/pain-point classification.
- Buyer intent score.
- Viral risk score.
- Creative recommendation engine.

### Version 0.8: Monitoring and Alerts

Goal: monitor active campaigns every 4 hours.

Deliverables:

- Scheduled monitoring job.
- Trend detection.
- Alert rules.
- Top 2-3 recommended actions per alert.
- Dashboard alert inbox.
- Telegram bot notifications.
- Dashboard notifications.
- Approval buttons for executable recommendations.

### Version 0.9: Experiment Planner

Goal: turn recommendations into structured experiments.

Deliverables:

- Experiment creation from agent recommendations.
- Hypothesis, variable, budget, duration, success metric.
- Experiment status tracking.
- Before/after comparison.
- Lessons learned saved to knowledge base.

### Version 0.9.5: Campaign Playbook Builder

Goal: let the user configure reusable campaign playbooks instead of hardcoding campaign-specific assumptions.

Deliverables:

- Dashboard playbook settings page.
- Telegram bot flow for creating/updating a playbook.
- Dynamic Segment/VSL configuration with no fixed segment count.
- Target audience input per segment.
- Pain point and offer-angle input per segment.
- Budget and scaling configuration.
- Success metric selection.
- Guardrail metric selection.
- Sales capacity configuration.
- Approval and alert channel configuration.
- Playbook version history.
- Ability to clone a previous playbook for a new campaign.

### Version 1.0: Approval-Based Meta Execution

Goal: prepare and execute Meta changes with user approval.

Deliverables:

- Draft campaign builder.
- Draft ad set builder.
- Creative upload workflow.
- Budget adjustment requests.
- Pause/scale recommendations.
- Approval queue.
- Telegram approval bot.
- Audit log of every action.

## 14. First Build Sequence

Recommended first GitHub pieces:

1. Commit this architecture/spec document.
2. Commit environment cleanup and README updates.
3. Fix existing dashboard data issues.
4. Add CRM import module.
5. Add three-segment funnel event API.
6. Add knowledge base and improved agent chat.
7. Add monitoring job.
8. Add approval-based execution.

## 15. Open Questions

These should be answered one by one before building the related version:

1. What are the exact names and URLs for the three landing pages?
2. What are the exact names and links for the three ChatPlace bots after creation?
3. Can the outsourced sales team add and confirm hidden Bitrix24 fields?
4. What columns will appear in the first Google Sheet/CSV export?
5. What should count as a qualified lead once the sales team shares stage names?
6. What are the final daily/monthly maximum budget limits for each campaign playbook?
7. Which Meta Ads changes should the agent be allowed to execute after approval in Version 1.0?
8. What Telegram account/group should receive agent alerts and approval buttons?
