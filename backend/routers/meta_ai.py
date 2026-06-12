"""Meta AI Capture routes.

The operator pastes the Ads Manager AI ("Analyze") panel text (or
screenshot-derived text); the Advisor summarizes and rates it, and the
Strategist scores it against the knowledge base and business context. Nothing
here executes or publishes anything.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException

from ..api_models import MetaAiCaptureRequest
from ..knowledge_base import load_knowledge_base
from ..meta_ai_advisor import analyze_capture
from ..meta_ai_capture_store import STORAGE_DIR as META_AI_STORAGE_DIR
from ..meta_ai_capture_store import list_captures, save_capture

router = APIRouter()


@router.get("/api/meta-ai/captures")
def meta_ai_captures() -> dict[str, Any]:
    return {"captures": list_captures(storage_dir=META_AI_STORAGE_DIR)}


@router.post("/api/meta-ai/captures")
def create_meta_ai_capture(request: MetaAiCaptureRequest) -> dict[str, Any]:
    text = " ".join(part for part in [request.sourceText, request.screenshotText] if part).strip()
    if not text:
        raise HTTPException(status_code=400, detail="Paste the Meta AI text or screenshot text before saving a capture.")

    created_at = datetime.now(timezone.utc)
    capture = {
        "id": f"meta_ai_{created_at.strftime('%Y%m%dT%H%M%S%fZ')}",
        "createdAt": created_at.isoformat(),
        "capturedBy": request.capturedBy,
        "objectLevel": request.objectLevel,
        "campaignId": request.campaignId,
        "campaignName": request.campaignName,
        "sourceText": request.sourceText,
        "screenshotText": request.screenshotText,
    }
    capture["analysis"] = analyze_capture(capture, knowledge=load_knowledge_base())
    saved = save_capture(capture, storage_dir=META_AI_STORAGE_DIR)
    return {"ok": True, "capture": saved}
