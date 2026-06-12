from backend.campaign_specific_analysis import rank_rows


def _row(adset_id, adset_name, *, spend, clicks, leads):
    return {
        "adset_id": adset_id,
        "adset_name": adset_name,
        "spend": str(spend),
        "clicks": str(clicks),
        "actions": [{"action_type": "lead", "value": str(leads)}],
    }


def test_rank_rows_prefers_proven_volume_over_marginally_cheaper_cpl():
    # Equal lead rate (10%); B is 10x volume at a marginally higher CPL ($5.10 vs $5.00).
    # Quality+volume ranking must put the proven high-volume winner (B) first, unlike a
    # pure-CPL sort which would pick A.
    rows = [
        _row("a", "Low volume", spend=5000, clicks=10000, leads=1000),   # CPL 5.00
        _row("b", "High volume", spend=51000, clicks=100000, leads=10000),  # CPL 5.10
    ]

    ranked = rank_rows(rows, ["adset_id", "adset_name"])

    assert ranked[0]["label"] == "High volume"
    assert ranked[0]["leads"] == 10000


def test_rank_rows_deprioritizes_low_sample_ad_sets():
    # A tiny ad set with a great lead rate must not outrank a well-sampled one.
    rows = [
        _row("thin", "Thin 100pct", spend=2, clicks=10, leads=10),        # 100% lead rate, 10 clicks
        _row("solid", "Solid sample", spend=200, clicks=2000, leads=400),  # 20% lead rate, 2000 clicks
    ]

    ranked = rank_rows(rows, ["adset_id", "adset_name"])

    assert ranked[0]["label"] == "Solid sample"
    assert ranked[-1]["label"] == "Thin 100pct"
