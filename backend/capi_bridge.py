"""Token bridge: turn an in-bot phone capture into a Meta-matchable conversion.

The problem this solves. A Telegram bot has no browser, so it cannot fire a pixel. A
server-side event sent with only a hashed phone reaches Meta with a match quality around
4.8/10 — Meta receives it but cannot join it to the ad click that produced it, so it can
neither attribute nor optimize for it. (Measured: 2,944 real CRM leads in Jun–Jul, of which
Meta attributed 129.)

The fix is a per-user token minted on the landing page and carried the whole way:

    landing page                     Telegram bot                  here
    ------------                     ------------                  ----
    mint TOKEN (v_...)               ?start=<TOKEN>                lookup TOKEN -> fbp/fbc
    POST /api/funnel/events   ---->  request_phone         ---->   send CAPI with BOTH the
    with fbp + fbc + UA              POST /api/capi/lead           hashed phone AND fbp/fbc

`remember_identity` stores the browser side; `lookup_identity` retrieves it when the bot
reports the phone. Everything else here is hashing and payload shaping.

Storage is a small append-only JSONL kept separate from funnel_events.jsonl on purpose:
that file is tens of MB and streaming it per lookup is O(total events) per request, which is
what wedged the VM's memory in June. This one is pruned to CAPI_IDENTITY_TTL_DAYS (Meta only
accepts events up to 7 days old, so nothing older is useful) and cached in-process.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import httpx

from .meta_client import MetaApiError, MetaConfig, extract_meta_error, get_ssl_context

ROOT = Path(__file__).resolve().parents[1]
STORAGE_DIR = ROOT / "storage"
IDENTITY_FILENAME = "capi_identity.jsonl"

TOKEN_PATTERN = re.compile(r"\bv_[A-Za-z0-9_-]{3,64}\b")

# Meta's 7-day limit applies to event_time, NOT to how long an identity stays useful: a lead
# that a rep qualifies three weeks after capture still fires a QualifiedLead dated *today*,
# and that event still needs the original fbp/fbc to match. So retention tracks the sales
# cycle, not the event window. ~30 days at current volume is a few MB in memory.
IDENTITY_TTL_SECONDS = int(os.getenv("CAPI_IDENTITY_TTL_DAYS", "30")) * 86_400
# Rewrite (rather than append) once the live set grows past this, so the file cannot
# grow without bound on a long-running process.
IDENTITY_COMPACT_AT = 50_000

# Cached per storage path so tests using tmp_path never share state with each other.
_CACHE: dict[str, dict[str, dict[str, Any]]] = {}


# --------------------------------------------------------------------------- hashing


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_text(value: Any) -> str | None:
    """Meta's normalization for name/country style fields: trim, lowercase, then SHA-256."""
    if value in (None, ""):
        return None
    text = str(value).strip().lower()
    return sha256_hex(text) if text else None


def normalize_phone(value: Any, *, default_country_code: str | None = None) -> str | None:
    """Digits only, with country code, no '+' — Meta's required phone form.

    ChatPlace sends `+{{ phone }}`, and Telegram's shared contact usually already carries the
    country code. A bare 9-digit Uzbek number gets the default prefixed so it still matches.
    """
    if value in (None, ""):
        return None
    digits = re.sub(r"\D", "", str(value))
    if not digits:
        return None
    cc = (default_country_code or os.getenv("CAPI_DEFAULT_COUNTRY_CODE", "998")).strip()
    if cc and len(digits) == 9:
        digits = f"{cc}{digits}"
    return digits


def hash_phone(value: Any, *, default_country_code: str | None = None) -> str | None:
    normalized = normalize_phone(value, default_country_code=default_country_code)
    return sha256_hex(normalized) if normalized else None


def extract_token(value: Any) -> str | None:
    """Pull the v_ token out of anything the bot might send.

    Handles the raw Telegram start command ("/start v_abc123"), a bare token, and a full
    t.me URL with ?start=. Returns None rather than guessing when there is no token —
    a wrong token would attach one person's conversion to another person's ad click.
    """
    if value in (None, ""):
        return None
    match = TOKEN_PATTERN.search(str(value))
    return match.group(0) if match else None


# --------------------------------------------------------------------------- identity store


def _resolve_dir(storage_dir: Path | None) -> Path:
    """Read STORAGE_DIR at call time, not at import time.

    A `storage_dir: Path = STORAGE_DIR` default binds once when the module loads, which makes
    the location impossible to override afterwards — by a test, or by a deploy that moves the
    storage volume."""
    return storage_dir if storage_dir is not None else STORAGE_DIR


def _identity_path(storage_dir: Path) -> Path:
    return storage_dir / IDENTITY_FILENAME


def _load_cache(storage_dir: Path) -> dict[str, dict[str, Any]]:
    key = str(storage_dir.resolve())
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    entries: dict[str, dict[str, Any]] = {}
    path = _identity_path(storage_dir)
    if path.exists():
        cutoff = time.time() - IDENTITY_TTL_SECONDS
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    row = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                token = row.get("token")
                if not token or float(row.get("ts") or 0) < cutoff:
                    continue
                # Last write wins: a repeat landing visit refreshes fbc/fbp.
                entries[token] = row
    _CACHE[key] = entries
    return entries


def reset_identity_cache() -> None:
    """Drop the in-process cache. Used by tests; harmless in production."""
    _CACHE.clear()


def remember_identity(payload: dict[str, Any], *, storage_dir: Path | None = None) -> dict[str, Any] | None:
    """Record the browser identity behind a token. Returns the stored row, or None when the
    payload carries no token or no usable identifier (in which case there is nothing to join on
    later and writing a row would only add noise)."""
    storage_dir = _resolve_dir(storage_dir)
    token = extract_token(
        payload.get("visitor_id") or payload.get("visitorId") or payload.get("token") or payload.get("start_payload")
    )
    if not token:
        return None

    row = {
        "token": token,
        "ts": time.time(),
        "fbp": _clean(payload.get("fbp")),
        "fbc": _clean(payload.get("fbc")),
        "userAgent": _clean(payload.get("user_agent") or payload.get("userAgent")),
        "ip": _clean(payload.get("ip") or payload.get("client_ip_address")),
        "aud": _clean(payload.get("aud")),
        "eventSourceUrl": _clean(payload.get("event_source_url") or payload.get("url")),
    }
    row = {key: value for key, value in row.items() if value not in (None, "")}
    if not any(row.get(field) for field in ("fbp", "fbc", "ip", "userAgent")):
        # No browser identifier -> nothing that would raise match quality. Skip.
        return None

    cache = _load_cache(storage_dir)
    cache[token] = row

    storage_dir.mkdir(parents=True, exist_ok=True)
    path = _identity_path(storage_dir)
    if len(cache) > IDENTITY_COMPACT_AT:
        _compact(path, cache)
    else:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def link_phone(phone: Any, token: str | None, *, storage_dir: Path | None = None) -> bool:
    """Attach a phone to an already-stored token.

    Called at capture time, when the bot reports both. Without it a later CRM status change —
    which knows only the phone — could never find the browser identity, and the delayed
    QualifiedLead/Purchase events would go out unmatched.
    """
    storage_dir = _resolve_dir(storage_dir)
    normalized = normalize_phone(phone)
    if not (normalized and token):
        return False
    cache = _load_cache(storage_dir)
    row = cache.get(token)
    if row is None:
        return False
    row["phone"] = normalized
    storage_dir.mkdir(parents=True, exist_ok=True)
    with _identity_path(storage_dir).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return True


def lookup_identity_by_phone(phone: Any, *, storage_dir: Path | None = None) -> dict[str, Any] | None:
    """Find the stored browser identity from a phone number alone."""
    normalized = normalize_phone(phone)
    if not normalized:
        return None
    for row in _load_cache(_resolve_dir(storage_dir)).values():
        if row.get("phone") == normalized:
            return row
    return None


def lookup_identity(token: str | None, *, storage_dir: Path | None = None) -> dict[str, Any] | None:
    if not token:
        return None
    return _load_cache(_resolve_dir(storage_dir)).get(token)


def _compact(path: Path, cache: dict[str, dict[str, Any]]) -> None:
    cutoff = time.time() - IDENTITY_TTL_SECONDS
    fresh = {token: row for token, row in cache.items() if float(row.get("ts") or 0) >= cutoff}
    cache.clear()
    cache.update(fresh)
    with path.open("w", encoding="utf-8") as handle:
        for row in fresh.values():
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _clean(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


# --------------------------------------------------------------------------- CAPI payload


def build_capi_event(
    *,
    event_name: str,
    token: str | None,
    phone: Any = None,
    first_name: Any = None,
    identity: dict[str, Any] | None = None,
    country: str | None = "uz",
    aud: str | None = None,
    event_time: int | None = None,
    action_source: str | None = None,
    event_source_url: str | None = None,
) -> dict[str, Any]:
    """Shape one Conversions API event.

    Hashed fields (ph/fn/external_id/country) go through SHA-256; fbp and fbc must NOT be
    hashed — Meta matches those literally, and hashing them silently destroys the match.
    """
    identity = identity or {}
    user_data: dict[str, Any] = {}

    phone_hash = hash_phone(phone)
    if phone_hash:
        user_data["ph"] = [phone_hash]
    name_hash = hash_text(first_name)
    if name_hash:
        user_data["fn"] = [name_hash]
    country_hash = hash_text(country)
    if country_hash:
        user_data["country"] = [country_hash]
    if token:
        user_data["external_id"] = [sha256_hex(token)]

    # Unhashed, and the whole point of the bridge.
    if identity.get("fbp"):
        user_data["fbp"] = identity["fbp"]
    if identity.get("fbc"):
        user_data["fbc"] = identity["fbc"]
    if identity.get("ip"):
        user_data["client_ip_address"] = identity["ip"]
    if identity.get("userAgent"):
        user_data["client_user_agent"] = identity["userAgent"]

    resolved_source = action_source or os.getenv("META_CAPI_ACTION_SOURCE", "website").strip() or "website"
    event: dict[str, Any] = {
        "event_name": event_name,
        "event_time": int(event_time or time.time()),
        "action_source": resolved_source,
        "user_data": user_data,
    }
    if token:
        # Stable id so a ChatPlace retry dedupes instead of double-counting.
        event["event_id"] = f"{event_name.lower()}_{token}"

    if resolved_source == "website":
        url = event_source_url or identity.get("eventSourceUrl") or os.getenv("META_CAPI_SOURCE_URL", "").strip()
        if url:
            event["event_source_url"] = url

    custom = {key: value for key, value in {"aud": aud or identity.get("aud")}.items() if value}
    if custom:
        event["custom_data"] = custom
    return event


def match_keys(event: dict[str, Any]) -> list[str]:
    """Which identifiers this event carries — the readable version of match quality."""
    return sorted(event.get("user_data", {}).keys())


def is_matchable(event: dict[str, Any]) -> bool:
    """True when the event carries at least one browser identifier, i.e. Meta can plausibly
    tie it back to an ad click. A phone-only event is deliverable but near-unattributable."""
    return any(key in event.get("user_data", {}) for key in ("fbp", "fbc"))


# --------------------------------------------------------------------------- transport


async def send_capi_events(
    config: MetaConfig,
    events: list[dict[str, Any]],
    *,
    dataset_id: str | None = None,
    test_event_code: str | None = None,
) -> dict[str, Any]:
    """POST events to the pixel's /events edge. Raises MetaApiError on a non-2xx."""
    pixel = (dataset_id or config.pixel_id or "").strip()
    if not pixel:
        raise MetaApiError("META_PIXEL_ID is required to send Conversions API events.")
    if not config.access_token:
        raise MetaApiError("META_ACCESS_TOKEN is required to send Conversions API events.")

    url = f"https://graph.facebook.com/{config.api_version}/{pixel}/events"
    form: dict[str, Any] = {
        "data": json.dumps(events, separators=(",", ":")),
        "access_token": config.access_token,
    }
    code = (test_event_code or os.getenv("META_CAPI_TEST_EVENT_CODE", "")).strip()
    if code:
        form["test_event_code"] = code

    try:
        async with httpx.AsyncClient(timeout=30, verify=get_ssl_context()) as client:
            response = await client.post(url, data=form)
    except httpx.HTTPError as error:
        raise MetaApiError(f"Could not reach the Meta Conversions API: {error}") from error

    if response.status_code >= 400:
        raise MetaApiError(extract_meta_error(response))
    try:
        return response.json()
    except ValueError:
        return {"events_received": len(events)}
