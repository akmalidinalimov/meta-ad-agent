# VSL Watch Metrics (YouTube)

`GET /api/vsl?days=N` returns the VSL engagement metrics shown on the dashboard:

```json
{ "ok": true, "configured": true, "videoId": "...", "days": 30,
  "views": 2000, "viewsWatched50": 350, "watchRate50": 17.5,
  "hasRetention": true, "source": "youtube_analytics", "refreshedAt": "ISO" }
```

- **views** — total views, exactly what YouTube counts (Data API `statistics.viewCount`, or the Analytics `views` metric when only OAuth is configured).
- **viewsWatched50 / watchRate50** — the count and percent of views still watching at the **50% mark**, derived from YouTube's audience-retention curve (`audienceWatchRatio` at `elapsedVideoTimeRatio ≈ 0.5`). `audienceWatchRatio` is (midpoint watches ÷ total views); it can exceed 1 on rewatches, so it is clamped to ≤100% before becoming a viewer count. This is the honest "how many actually watched" number — e.g. 2000 views × 0.175 = **350**.
- All calls are **read-only**.

## Configuration (backend env)

| Var | Needed for | Notes |
|---|---|---|
| `YOUTUBE_VSL_VIDEO_ID` | everything | The VSL video id (the `v=` part of the watch URL). |
| `YOUTUBE_API_KEY` | views (easy path) | A plain Data API v3 key. Gives total views, no retention. |
| `YOUTUBE_OAUTH_CLIENT_ID` / `_SECRET` / `_REFRESH_TOKEN` | the 50%-watched metric | OAuth for the **YouTube Analytics API** on **your own channel**. |

If only the API key is set, the dashboard shows Views (retention is null). If OAuth is set, it shows Views + 50%-watched. Until any of this is set, `/api/vsl` returns `configured: false` and the panel shows a "connect YouTube" state — nothing breaks.

## One-time OAuth refresh-token setup (for the 50%-watched metric)

The Analytics API needs a user-authorized token for the channel that owns the video. Generate a refresh token once:

1. In Google Cloud Console, enable **YouTube Analytics API** + **YouTube Data API v3**.
2. Create an **OAuth client ID** (type: Web application). Note the client id + secret. Add `https://developers.google.com/oauthplayground` as an authorized redirect URI.
3. Open the [OAuth Playground](https://developers.google.com/oauthplayground), gear icon → "Use your own OAuth credentials", paste client id + secret.
4. Authorize the scope `https://www.googleapis.com/auth/yt-analytics.readonly` (sign in as the channel owner).
5. Exchange the code for tokens; copy the **refresh token**.
6. Put `YOUTUBE_OAUTH_CLIENT_ID`, `YOUTUBE_OAUTH_CLIENT_SECRET`, `YOUTUBE_OAUTH_REFRESH_TOKEN`, and `YOUTUBE_VSL_VIDEO_ID` in the backend env. The backend refreshes the access token itself on each read.

The dashboard renders the VSL panel only when `VITE_CRM_ENABLED`/the redesign flag is on (it sits in the redesigned funnel section).
