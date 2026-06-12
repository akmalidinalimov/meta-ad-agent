"""Creative recommendations for the draft campaign proposal.

For each recommended audience this module answers two questions the operator
always asks next: *which existing creatives should I reuse?* and *what NEW
angles should I produce?*

Two entry points:

* ``build_recommended_creatives`` — SYNC and fully DETERMINISTIC. It reuses the
  already-computed ``analysis["topAds"]`` (enriched creative metadata + quality
  scores from the analysis engine) to pick the best non-fatigued existing
  creatives per segment, and derives 2-3 new-angle briefs from the account's
  winning creative themes/hooks. This is the only path the sync draft builder
  calls, so the proposal is reproducible with no network/LLM.

* ``generate_creative_angle_briefs`` — OPTIONAL async enhancer for the future
  proactive engine (WS-E). It asks the configured LLM (via the ``reason()``
  seam) for richer briefs and falls back to the deterministic briefs whenever
  the model is unavailable / returns unparseable output. Any cited METRIC or
  entity must come from the analysis (grounding spirit preserved).
"""

from __future__ import annotations

import json
from typing import Any

from .llm_provider import reason
from .llm_reasoner import _usable

# A creative whose quality has decayed is not worth re-testing as-is. We treat an
# ad as "fatigued" when its hold rate has collapsed (viewers drop before the
# offer) or an explicit fatigue flag/score is present. Conservative so we never
# silently drop a genuinely strong performer.
FATIGUE_HOLD_RATE_FLOOR = 18.0
FATIGUE_SCORE_CEILING = 70.0  # fatigueScore (0-100) at/above this = clearly fatigued


def as_num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _creative_meta(ad: dict[str, Any]) -> dict[str, Any]:
    """The enriched ``creative`` sub-object attached by ``enrich_ads`` (may be absent)."""
    meta = ad.get("creative")
    return meta if isinstance(meta, dict) else {}


def _ad_label(ad: dict[str, Any]) -> str:
    keys = ad.get("keys", {}) or {}
    meta = _creative_meta(ad)
    return str(
        keys.get("ad_name")
        or meta.get("name")
        or ad.get("label")
        or keys.get("ad_id")
        or "Unknown creative"
    )


def _creative_id(ad: dict[str, Any]) -> str | None:
    meta = _creative_meta(ad)
    keys = ad.get("keys", {}) or {}
    return meta.get("id") or keys.get("ad_id") or ad.get("creativeId")


def derive_format(ad: dict[str, Any]) -> str:
    """Best-effort creative format from whatever metadata is present."""
    if ad.get("format"):
        return str(ad["format"])
    meta = _creative_meta(ad)
    object_type = str(meta.get("objectType") or "").upper()
    if "VIDEO" in object_type or meta.get("videoId") or ad.get("hookRate") is not None:
        return "video"
    if "IMAGE" in object_type or "PHOTO" in object_type:
        return "image"
    if "CAROUSEL" in object_type or "MULTI" in object_type:
        return "carousel"
    return "video" if ad.get("hookRate") is not None else "image"


def derive_theme(ad: dict[str, Any]) -> str:
    """Coarse content theme. Uses an explicit field when the upstream scorer set
    one, otherwise infers from the creative title/body, otherwise a safe default."""
    if ad.get("theme"):
        return str(ad["theme"])
    if ad.get("type"):
        return str(ad["type"])
    meta = _creative_meta(ad)
    text = " ".join(
        str(meta.get(field) or "") for field in ("title", "body", "name")
    ).lower()
    if any(word in text for word in ("earn", "income", "money", "salary", "$")):
        return "Income outcome"
    if any(word in text for word in ("how", "step", "tutorial", "learn", "guide")):
        return "Education / how-to"
    if any(word in text for word in ("story", "journey", "before", "after", "result")):
        return "Transformation story"
    if any(word in text for word in ("review", "testimonial", "client", "student")):
        return "Social proof"
    return "Outcome demo"


def derive_hook_type(ad: dict[str, Any]) -> str:
    """Coarse hook style, from an explicit field or the measured hook rate."""
    if ad.get("hookType"):
        return str(ad["hookType"])
    hook_rate = ad.get("hookRate")
    if hook_rate is None:
        return "Static hook"
    if as_num(hook_rate) >= 25.0:
        return "Strong pattern-interrupt"
    if as_num(hook_rate) >= 15.0:
        return "Question / curiosity hook"
    return "Soft open"


def is_fatigued(ad: dict[str, Any]) -> bool:
    if ad.get("fatigued") is True:
        return True
    fatigue_score = ad.get("fatigueScore")
    if fatigue_score is not None and as_num(fatigue_score) >= FATIGUE_SCORE_CEILING:
        return True
    hold_rate = ad.get("holdRate")
    if hold_rate is not None and as_num(hold_rate) < FATIGUE_HOLD_RATE_FLOOR:
        return True
    return False


def _quality_of(ad: dict[str, Any]) -> float:
    return as_num(ad.get("qualityScore"))


def _best_existing_creatives(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    """Top ads sorted by quality (desc), with fatigued ones removed."""
    top_ads = [ad for ad in (analysis.get("topAds", []) or []) if isinstance(ad, dict)]
    healthy = [ad for ad in top_ads if not is_fatigued(ad)]
    return sorted(
        healthy,
        key=lambda ad: (_quality_of(ad), as_num(ad.get("purchases")), as_num(ad.get("leads"))),
        reverse=True,
    )


def _creative_row(segment: str, ad: dict[str, Any]) -> dict[str, Any]:
    name = _ad_label(ad)
    quality = round(_quality_of(ad), 2)
    hook_rate = ad.get("hookRate")
    rationale_bits = [f"quality {quality:g}"]
    if hook_rate is not None:
        rationale_bits.append(f"hook {as_num(hook_rate):.0f}%")
    if as_num(ad.get("purchases")) > 0:
        rationale_bits.append("has attributed purchases")
    elif as_num(ad.get("leads")) > 0:
        rationale_bits.append(f"{int(as_num(ad.get('leads')))} leads")
    return {
        "segment": segment,
        "creativeId": _creative_id(ad),
        "name": name,
        "format": derive_format(ad),
        "theme": derive_theme(ad),
        "hookType": derive_hook_type(ad),
        "qualityScore": quality,
        "rationale": f"Reuse {name}: " + ", ".join(rationale_bits) + ".",
    }


def _winning_signals(analysis: dict[str, Any]) -> dict[str, Any]:
    """The account's proven creative DNA: top themes, hooks, formats, plus the
    single best-performing creative (for grounded copy references)."""
    ranked = _best_existing_creatives(analysis)
    themes: list[str] = []
    hooks: list[str] = []
    formats: list[str] = []
    for ad in ranked:
        for value, bucket in (
            (derive_theme(ad), themes),
            (derive_hook_type(ad), hooks),
            (derive_format(ad), formats),
        ):
            if value and value not in bucket:
                bucket.append(value)
    interests = [
        str(i.get("label"))
        for i in (analysis.get("audience", {}) or {}).get("interests", []) or []
        if i.get("label")
    ]
    return {
        "themes": themes,
        "hooks": hooks,
        "formats": formats,
        "interests": interests,
        "best": ranked[0] if ranked else None,
        "topFormat": formats[0] if formats else "video",
    }


def build_new_angle_briefs(
    analysis: dict[str, Any],
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Deterministic 2-3 new-angle briefs derived from the account's winning DNA.

    Each brief is {angle, hook, format, whyItMightWork}. Copy may be invented, but
    any reference to a winning theme/format/interest is grounded in the analysis.
    """
    signals = _winning_signals(analysis)
    top_format = signals["topFormat"]
    lead_theme = signals["themes"][0] if signals["themes"] else "Outcome demo"
    interest = signals["interests"][0] if signals["interests"] else None
    interest_phrase = f" for {interest} buyers" if interest else ""

    catalog = [
        {
            "angle": "Outcome proof",
            "hook": f"\"Here's the exact result this got{interest_phrase} in 14 days.\"",
            "format": top_format,
            "whyItMightWork": (
                f"Doubles down on the winning '{lead_theme}' theme with a concrete, "
                "time-boxed proof point — proof beats promises for cold buyers."
            ),
        },
        {
            "angle": "Objection-handling",
            "hook": "\"You think you need experience to start. You don't — here's why.\"",
            "format": top_format,
            "whyItMightWork": (
                "Names the top buyer objection in the first 3s, then dismantles it; "
                "lifts hold rate by giving skeptics a reason to keep watching."
            ),
        },
        {
            "angle": "Founder POV / authority",
            "hook": "\"I'd start completely differently if I had to do this again today.\"",
            "format": top_format,
            "whyItMightWork": (
                "A first-person authority angle adds trust the existing winners lack, "
                "and tends to read as organic rather than an ad."
            ),
        },
        {
            "angle": "Fast how-to",
            "hook": "\"Do these 3 steps before you spend a dollar on this.\"",
            "format": top_format,
            "whyItMightWork": (
                "A how-to angle complements the proven outcome creatives by selling the "
                "method, widening the angle mix without abandoning what works."
            ),
        },
    ]
    return catalog[: max(2, min(limit, len(catalog)))]


def build_recommended_creatives(
    analysis: dict[str, Any] | None,
    segment_labels: list[str] | None,
    per_segment: int = 3,
) -> list[dict[str, Any]]:
    """For each segment label, recommend existing creatives to reuse + new briefs.

    SYNC and DETERMINISTIC. Returns a list of per-segment recommendation blocks::

        {
          "segment": <label>,
          "reuseExisting": [ {segment, creativeId, name, format, theme, hookType,
                              qualityScore, rationale}, ... up to per_segment ],
          "newAngleBriefs": [ {angle, hook, format, whyItMightWork}, ... 2-3 ],
        }

    Fully defensive: returns ``[]`` when there are no segments; per-segment
    ``reuseExisting`` is ``[]`` when the analysis carries no usable creatives, but
    ``newAngleBriefs`` are still produced from whatever winning signals exist.
    """
    analysis = analysis or {}
    labels = [str(label) for label in (segment_labels or []) if label]
    if not labels:
        return []

    ranked = _best_existing_creatives(analysis)
    per_segment = max(0, int(per_segment))
    briefs = build_new_angle_briefs(analysis)

    blocks: list[dict[str, Any]] = []
    for label in labels:
        # Deterministic per-segment selection: same global quality ordering, sliced
        # to per_segment. (Segment-specific performance is not in topAds, so the
        # best-overall non-fatigued creatives are the defensible reuse picks for each.)
        reuse = [_creative_row(label, ad) for ad in ranked[:per_segment]]
        blocks.append(
            {
                "segment": label,
                "reuseExisting": reuse,
                "newAngleBriefs": briefs,
            }
        )
    return blocks


# --- Optional async enhancer (for the proactive engine; NOT called by the sync builder) ---


def _strict_json_briefs(text: str) -> list[dict[str, Any]] | None:
    """Parse a strict-JSON brief list out of model output, tolerating fences/prose."""
    if not text:
        return None
    candidate = text.strip()
    # Strip a ```json ... ``` fence if present.
    if candidate.startswith("```"):
        candidate = candidate.strip("`")
        if candidate.lower().startswith("json"):
            candidate = candidate[4:]
    # Narrow to the outermost JSON array if there is surrounding prose.
    start = candidate.find("[")
    end = candidate.rfind("]")
    if start != -1 and end != -1 and end > start:
        candidate = candidate[start : end + 1]
    try:
        parsed = json.loads(candidate)
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, list):
        return None
    briefs: list[dict[str, Any]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        angle = item.get("angle")
        hook = item.get("hook")
        if not angle or not hook:
            continue
        briefs.append(
            {
                "angle": str(angle),
                "hook": str(hook),
                "format": str(item.get("format") or "video"),
                "whyItMightWork": str(item.get("whyItMightWork") or item.get("why") or ""),
            }
        )
    return briefs or None


async def generate_creative_angle_briefs(
    analysis: dict[str, Any] | None,
    segment_labels: list[str] | None,
    market_angles: list[str] | None = None,
) -> list[dict[str, Any]]:
    """LLM-enhanced new-angle briefs, with a deterministic fallback.

    Asks the configured reasoning provider for richer briefs grounded in the
    account's winning themes/hooks (and optional external ``market_angles``).
    Returns the deterministic ``build_new_angle_briefs`` output whenever the model
    is unavailable (no key), errors, or returns unparseable JSON — so the suite
    passes with no API key and the proactive engine always gets usable briefs.
    """
    analysis = analysis or {}
    fallback = build_new_angle_briefs(analysis)

    signals = _winning_signals(analysis)
    evidence = {
        "winningThemes": signals["themes"],
        "winningHooks": signals["hooks"],
        "winningFormats": signals["formats"],
        "topInterests": signals["interests"][:5],
        "proposedSegments": [str(s) for s in (segment_labels or []) if s],
        "marketAngles": [str(a) for a in (market_angles or []) if a],
    }
    system = (
        "You are a direct-response creative strategist for Meta video ads. "
        "Propose 3 fresh ad angles to TEST next, grounded in the account's proven "
        "winning themes and hooks. You may invent copy, but any cited metric, "
        "interest, or named entity must come from the provided evidence. "
        "Never recommend publishing or spending without operator approval. "
        "Respond with STRICT JSON only: a list of objects, each with keys "
        "angle, hook, format, whyItMightWork."
    )
    user = (
        "Account creative evidence (your only source of truth for named entities/metrics):\n"
        f"{json.dumps(evidence, ensure_ascii=False)[:8000]}\n\n"
        "Return STRICT JSON: a list of 3 {angle, hook, format, whyItMightWork} objects."
    )

    try:
        result = await reason([{"role": "user", "content": user}], system=system)
    except Exception:  # noqa: BLE001 - never let the enhancer raise; degrade instead
        return fallback

    usable = _usable(result)
    if not usable:
        return fallback
    parsed = _strict_json_briefs(usable)
    return parsed or fallback
