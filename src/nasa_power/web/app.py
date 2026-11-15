"""FastAPI backend serving Farm Memory API and accessible HTML/JS frontend."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

import requests
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from ..advisor import (
    QUESTION_LIBRARY,
    FarmMemoryRecord,
    FarmMemoryStore,
    NasaPowerDailyFetcher,
    compare_rotations,
    handle_farmer_chat,
    load_crop_catalog,
)

STATIC_DIR = Path(__file__).parent / "static"
DISTRICTS_PATH = Path("data/kedah_districts.geojson")

app = FastAPI(title="Farm Memory — Crop-Rotation Decision Support", version="0.1.0")

_fetcher = NasaPowerDailyFetcher()
_store = FarmMemoryStore()


class CompareRequest(BaseModel):
    farm_id: str = "farm_001"
    locality: str = "Kota Setar (Kampung Teluk Bagan)"
    latitude: float = Field(default=6.0704075, ge=-90.0, le=90.0)
    longitude: float = Field(default=100.3557400, ge=-180.0, le=180.0)
    planting_month: int = Field(default=1, ge=1, le=12)
    scenario: str = Field(
        default="historical_average",
        pattern="^(historical_average|dry_planting|heavy_rain_harvest|hot_season)$",
    )
    last_crop: str = "unknown"
    irrigation: str = "unknown"
    waterlogging_duration: str = "unknown"
    flooded_last_season: str = "unknown"
    soil_feel: str = "unknown"
    soil_ph_known: str = "unknown"
    priority: str = "lower_risk"
    field_problems: str = "unknown"
    trouble_spot: str = "unknown"
    labour: str = "unknown"
    field_observations: list[dict[str, str]] = Field(default_factory=list)


class ChatRequest(BaseModel):
    farm_id: str = "farm_001"
    message: str
    language: Literal["en", "ms"] = "en"
    comparison: dict[str, Any] | None = None


@app.get("/", include_in_schema=False)
def serve_index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/districts")
def get_districts() -> JSONResponse:
    if not DISTRICTS_PATH.exists():
        raise HTTPException(status_code=404, detail="Kedah districts GeoJSON not found.")
    return JSONResponse(content=json.loads(DISTRICTS_PATH.read_text(encoding="utf-8")))


@app.get("/api/crops")
def get_crops() -> dict[str, Any]:
    return {"crops": load_crop_catalog()}


@app.get("/api/questions")
def get_questions() -> dict[str, Any]:
    return {"questions": QUESTION_LIBRARY}


@app.get("/api/farms/{farm_id}")
def get_farm(farm_id: str) -> FarmMemoryRecord:
    rec = _store.get(farm_id)
    if rec is None:
        return FarmMemoryRecord(farm_id=farm_id)
    return rec


@app.post("/api/farms/{farm_id}")
def save_farm(farm_id: str, record: FarmMemoryRecord) -> FarmMemoryRecord:
    record.farm_id = farm_id
    return _store.save(record)


@app.delete("/api/farms/{farm_id}")
def delete_farm(farm_id: str) -> dict[str, bool]:
    return {"deleted": _store.delete(farm_id)}


@app.get("/api/farms/{farm_id}/export")
def export_farm(farm_id: str) -> JSONResponse:
    """Download the farmer's stored Farm Memory record as a JSON attachment."""
    rec = _store.get(farm_id) or FarmMemoryRecord(farm_id=farm_id)
    safe_id = "".join(c for c in farm_id if c.isalnum() or c in ("-", "_")) or "farm_001"
    return JSONResponse(
        content=rec.model_dump(),
        headers={"Content-Disposition": f'attachment; filename="{safe_id}_farm_memory.json"'},
    )


@app.post("/api/voice/transcribe")
async def transcribe_voice(audio: UploadFile = File(...)) -> dict[str, Any]:
    """Optional backend-only speech-to-text proxy; discards audio buffer immediately."""
    api_key = os.getenv("OPENAI_API_KEY")
    raw_bytes = await audio.read()
    if not api_key:
        raise HTTPException(
            status_code=501,
            detail="OPENAI_API_KEY is not configured on the backend. Use browser speech or form choices.",
        )

    try:
        resp = requests.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_key}"},
            files={"file": (audio.filename or "clip.webm", raw_bytes, audio.content_type or "audio/webm")},
            data={"model": "gpt-4o-mini-transcribe"},
            timeout=30,
        )
        resp.raise_for_status()
        text = resp.json().get("text", "")
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Transcription failed: {exc}") from exc
    finally:
        # Never retain audio buffers on disk or in memory
        del raw_bytes

    return {"text": text, "audio_stored": False}


@app.post("/api/chat")
def chat_with_advisor(req: ChatRequest) -> dict[str, Any]:
    """Route open farmer questions without mutating FarmMemoryStore."""
    memory = _store.get(req.farm_id) or FarmMemoryRecord(farm_id=req.farm_id)
    return handle_farmer_chat(
        message=req.message,
        memory=memory,
        comparison=req.comparison,
        language=req.language,
    )


@app.post("/api/compare")
def compare(req: CompareRequest) -> dict[str, Any]:
    memory = FarmMemoryRecord(
        farm_id=req.farm_id,
        locality=req.locality,
        latitude=req.latitude,
        longitude=req.longitude,
        last_crop=req.last_crop,
        irrigation=req.irrigation,
        waterlogging_duration=req.waterlogging_duration,
        flooded_last_season=req.flooded_last_season,
        soil_feel=req.soil_feel,
        soil_ph_known=req.soil_ph_known,
        priority=req.priority,
        field_problems=req.field_problems,
        trouble_spot=req.trouble_spot,
        labour=req.labour,
        field_observations=req.field_observations,
    )
    try:
        climate = _fetcher.get_summary(
            latitude=req.latitude,
            longitude=req.longitude,
            planting_month=req.planting_month,
            scenario=req.scenario,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    result = compare_rotations(climate=climate, memory=memory)
    return asdict(result)
