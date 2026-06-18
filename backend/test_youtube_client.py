import asyncio

from backend.youtube_client import (
    YouTubeConfig,
    build_vsl_metrics,
    build_vsl_report,
    parse_retention_rows,
    parse_view_count,
    ratio_nearest_half,
)


def test_parse_view_count_reads_statistics():
    assert parse_view_count({"items": [{"statistics": {"viewCount": "2000"}}]}) == 2000
    assert parse_view_count({"items": []}) == 0
    assert parse_view_count({}) == 0


def test_parse_retention_rows_maps_columns_by_name():
    payload = {
        "columnHeaders": [{"name": "elapsedVideoTimeRatio"}, {"name": "audienceWatchRatio"}],
        "rows": [[0.0, 1.0], [0.49, 0.62], [0.51, 0.60], [1.0, 0.2]],
    }
    rows = parse_retention_rows(payload)
    assert (0.49, 0.62) in rows
    assert parse_retention_rows({"columnHeaders": [], "rows": []}) == []


def test_ratio_nearest_half_picks_closest_to_midpoint():
    rows = [(0.0, 1.0), (0.49, 0.62), (0.51, 0.60), (1.0, 0.2)]
    assert ratio_nearest_half(rows) == 0.62  # 0.49 is nearest 0.5
    assert ratio_nearest_half([]) is None


def test_build_vsl_metrics_50pct_watch():
    m = build_vsl_metrics(2000, 0.175)
    assert m["views"] == 2000
    assert m["viewsWatched50"] == 350   # 2000 * 0.175 (matches the real example)
    assert m["watchRate50"] == 17.5

    none = build_vsl_metrics(2000, None)
    assert none["views"] == 2000 and none["viewsWatched50"] is None and none["watchRate50"] is None

    clamp = build_vsl_metrics(100, 1.4)  # rewatch can push the ratio above 1
    assert clamp["viewsWatched50"] == 100 and clamp["watchRate50"] == 100.0


class FakeYouTubeTransport:
    def __init__(self, views, rows):
        self._views = views
        self._rows = rows
        self.calls = []

    async def fetch_views(self, video_id):
        self.calls.append(("views", video_id))
        return self._views

    async def fetch_retention_rows(self, video_id, days):
        self.calls.append(("retention", video_id, days))
        return self._rows


def _cfg(**kw):
    base = dict(api_key="k", oauth_client_id="", oauth_client_secret="", oauth_refresh_token="", video_id="vid123")
    base.update(kw)
    return YouTubeConfig(**base)


def test_build_vsl_report_data_only_has_views_no_retention():
    cfg = _cfg()  # api_key only, no oauth
    transport = FakeYouTubeTransport(2000, [(0.5, 0.5)])
    report = asyncio.run(build_vsl_report(transport=transport, config=cfg, days=30))
    assert report["views"] == 2000
    assert report["viewsWatched50"] is None       # no oauth -> no retention call
    assert report["hasRetention"] is False
    assert ("retention", "vid123", 30) not in transport.calls


def test_build_vsl_report_with_oauth_computes_50pct():
    cfg = _cfg(oauth_client_id="c", oauth_client_secret="s", oauth_refresh_token="r")
    transport = FakeYouTubeTransport(2000, [(0.0, 1.0), (0.5, 0.175), (1.0, 0.1)])
    report = asyncio.run(build_vsl_report(transport=transport, config=cfg, days=30))
    assert report["views"] == 2000
    assert report["viewsWatched50"] == 350
    assert report["watchRate50"] == 17.5
    assert report["hasRetention"] is True
    assert report["source"] == "youtube_analytics"
