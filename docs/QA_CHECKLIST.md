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
