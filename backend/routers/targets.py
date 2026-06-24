"""Operator KPI targets (goals) — read + update.

Account-level goals the 4-hourly digest and monitoring compare actuals against.
Updates are guarded by the same API key as the other write routes (no key set =
open in dev, as elsewhere).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..auth import require_api_key
from ..targets_store import load_targets, save_targets

router = APIRouter()


class TargetsUpdate(BaseModel):
    maxCpl: float | None = None
    minLeadRate: float | None = None
    maxCostPerStart: float | None = None
    minStartRate: float | None = None


@router.get("/api/targets")
def get_targets() -> dict[str, Any]:
    return {"targets": load_targets()}


@router.put("/api/targets", dependencies=[Depends(require_api_key)])
def put_targets(update: TargetsUpdate) -> dict[str, Any]:
    saved = save_targets(update.model_dump(exclude_unset=True))
    return {"ok": True, "targets": saved}
