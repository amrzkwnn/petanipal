import os
import uuid
from pathlib import Path
from typing import Annotated, Any, Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from schemas import (
    CropProfile,
    FarmMemory,
    LanguageCode,
    PendingConfirmation,
    QuestionItem,
    VoiceChatRequest,
    VoiceConfirmRequest,
    VoiceTurnResponse,
)
from services import (
    LibraryStore,
    MemoryStore,
    NasaPowerClimateService,
    OpenAIRealtimeService,
    OpenAIVoiceService,
    SupabaseMemoryStore,
    compare_rotations,
    load_geotanih_context,
)
from services.offline_router import route_offline
from services.openai_voice import LLMExtractionResult

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", override=True)
load_dotenv(override=True)
STATIC_DIR = BASE_DIR / "static"
if not STATIC_DIR.exists():
    STATIC_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="Farm Memory — Voice & Crop Library API",
    version="0.2.0",
    description="Multilingual (EN/MS) voice assistant, Supabase Farm Memory, and reviewed crop library for Sungai Petani, Kedah.",
)

allowed_origins = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173,http://localhost:8000").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

def _has_real_supabase() -> bool:
    url = (os.getenv("SUPABASE_URL") or "").strip()
    key = (os.getenv("SUPABASE_KEY") or "").strip()
    return bool(
        url
        and key
        and "your-project-ref" not in url
        and "your_supabase" not in key
    )


def _has_real_openai() -> bool:
    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    return bool(key and "your_openai" not in key)


libraries = LibraryStore(BASE_DIR / "data")
_is_vercel = bool(os.getenv("VERCEL"))
_climate_cache_dir = Path("/tmp/petanipal_climate_cache") if _is_vercel else (BASE_DIR / "storage" / "climate_cache")
_farm_memory_dir = Path("/tmp/petanipal_farm_memories") if _is_vercel else (BASE_DIR / "data" / "farm_memories")
climate_service = NasaPowerClimateService(cache_dir=_climate_cache_dir)
use_supabase = _has_real_supabase()
memory_store: MemoryStore | SupabaseMemoryStore = (
    SupabaseMemoryStore() if use_supabase else MemoryStore(storage_dir=_farm_memory_dir)
)
_voice_service: Optional[OpenAIVoiceService] = None
_realtime_service: Optional[OpenAIRealtimeService] = None


class LocationUpdateRequest(BaseModel):
    locality: str = "Sungai Petani, Kedah"
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class CompareRequest(BaseModel):
    farm_id: str
    candidate_crops: Optional[list[str]] = None
    scenario: str = "normal"


def get_auth_context(
    authorization: Annotated[Optional[str], Header()] = None,
) -> tuple[Optional[str], Optional[str]]:
    """Verify Supabase Bearer JWT when Supabase is configured; returns (user_id, token)."""
    if not isinstance(memory_store, SupabaseMemoryStore):
        return (None, None)
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization: Bearer <token> header.")
    token = authorization.split(" ", 1)[1].strip()
    user_id = memory_store.verify_user(token)
    return (user_id, token)


def get_voice_service() -> OpenAIVoiceService:
    global _voice_service
    if not _has_real_openai():
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is not configured on the backend.",
        )
    if _voice_service is None:
        _voice_service = OpenAIVoiceService()
    return _voice_service


def get_realtime_service() -> OpenAIRealtimeService:
    global _realtime_service
    if not _has_real_openai():
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is not configured on the backend.",
        )
    if _realtime_service is None:
        _realtime_service = OpenAIRealtimeService(climate_service=climate_service)
    return _realtime_service


def _geotanih_flags_for(farm: FarmMemory) -> set[str]:
    geo = load_geotanih_context(farm.location.locality or "Sungai Petani, Kedah")
    return set(geo.get("flags", []))


def _build_pending_confirmation(
    session_id: str,
    result: LLMExtractionResult,
) -> Optional[PendingConfirmation]:
    if not result.needs_confirmation or not result.extracted_target_field:
        return None

    proposed_value: object = result.extracted_value
    if result.extracted_target_field == "crop_history":
        proposed_value = {
            "crop_id": result.matched_crop_id,
            "raw_crop_name": result.human_label or result.extracted_value or "",
        }
    elif result.extracted_target_field == "field_observations":
        proposed_value = {
            "zone": result.observation_zone or "general",
            "event_type": result.observation_event_type or "general",
            "affected_crop": result.observation_affected_crop or result.matched_crop_id,
            "timing_or_duration": result.observation_timing_or_duration,
            "observation": result.human_label or result.extracted_value or "",
        }

    pending = PendingConfirmation(
        confirmation_id=uuid.uuid4().hex[:12],
        target_field=result.extracted_target_field,
        proposed_value=proposed_value,
        human_label=result.human_label or str(result.extracted_value or ""),
        confirmation_prompt=result.confirmation_prompt or result.assistant_text,
    )
    memory_store.save_pending(session_id, pending)
    return pending


async def _process_utterance(
    *,
    transcript: str,
    farm_id: str,
    session_id: str,
    language: LanguageCode,
    current_question_id: Optional[str],
    include_tts: bool,
    user_id: Optional[str],
    access_token: Optional[str],
) -> VoiceTurnResponse:
    farm = memory_store.get_or_create_farm(farm_id, user_id=user_id, access_token=access_token)
    farm.preferred_language = language
    gt_flags = _geotanih_flags_for(farm)

    current_q = (
        libraries.get_question(current_question_id)
        if current_question_id
        else libraries.get_next_question(farm, geotanih_flags=gt_flags)
    )
    lat = farm.location.latitude or 5.647
    lon = farm.location.longitude or 100.487
    climate = climate_service.get_summary(lat, lon, allow_network=_allow_nasa_network())
    comparison_context = compare_rotations(farm, libraries, climate=climate)

    llm_result: Optional[LLMExtractionResult] = None
    voice: Optional[OpenAIVoiceService] = None
    if _has_real_openai():
        try:
            voice = get_voice_service()
            llm_result = await voice.analyze_and_respond(
                transcript=transcript,
                language=language,
                farm=farm,
                current_question=current_q,
                crops=libraries.list_crops(),
                comparison_context=comparison_context,
            )
        except Exception:
            llm_result = None

    if llm_result is None:
        llm_result = route_offline(
            transcript=transcript,
            language=language,
            farm=farm,
            current_question=current_q,
            libraries=libraries,
            comparison_context=comparison_context,
        )

    pending = _build_pending_confirmation(session_id, llm_result)
    next_q = libraries.get_next_question(farm, geotanih_flags=gt_flags)

    tts_b64: Optional[str] = None
    if include_tts and llm_result.assistant_text and voice is not None:
        try:
            tts_b64 = await voice.synthesize_speech(llm_result.assistant_text)
        except Exception:
            tts_b64 = None

    return VoiceTurnResponse(
        session_id=session_id,
        language=language,
        transcript=transcript,
        question_type=llm_result.question_type,
        assistant_text=llm_result.assistant_text,
        tts_audio_base64=tts_b64,
        pending_confirmation=pending,
        next_question_id=next_q.question_id if next_q else None,
        answer_basis=llm_result.answer_basis,
        missing_info=llm_result.missing_info,
    )


@app.get("/", response_model=None)
async def root_page() -> FileResponse | HTMLResponse:
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return HTMLResponse("<h1>PetaniPal — Farm Memory</h1>")


def get_public_config_sync() -> dict[str, Any]:
    return {
        "supabase_url": os.getenv("SUPABASE_URL", "") if _has_real_supabase() else "",
        "supabase_anon_key": os.getenv("SUPABASE_ANON_KEY", os.getenv("SUPABASE_KEY", "")) if _has_real_supabase() else "",
        "supabase_enabled": isinstance(memory_store, SupabaseMemoryStore),
        "openai_configured": _has_real_openai(),
        "realtime_model": os.getenv("OPENAI_REALTIME_MODEL", "gpt-realtime-2.1-mini"),
    }


@app.get("/api/config")
async def get_public_config() -> dict[str, Any]:
    return get_public_config_sync()


@app.get("/health")
async def health() -> dict[str, object]:
    return {
        "status": "ok",
        "locality": libraries.crop_library.locality,
        "storage": "supabase" if isinstance(memory_store, SupabaseMemoryStore) else "local_json",
    }


@app.get("/api/crops", response_model=list[CropProfile])
async def list_crops() -> list[CropProfile]:
    return libraries.list_crops()


@app.get("/api/crops/{crop_id}", response_model=CropProfile)
async def get_crop(crop_id: str) -> CropProfile:
    crop = libraries.get_crop(crop_id)
    if crop is None:
        raise HTTPException(status_code=404, detail=f"Crop '{crop_id}' not found in reviewed library.")
    return crop


@app.get("/api/questions", response_model=list[QuestionItem])
async def list_questions() -> list[QuestionItem]:
    return libraries.list_questions()


def list_farms_sync(
    auth: tuple[Optional[str], Optional[str]] = (None, None),
) -> dict[str, Any]:
    user_id, access_token = auth
    return {"farms": memory_store.list_farms(user_id=user_id, access_token=access_token)}


@app.get("/api/farms")
async def list_farms(
    auth: Annotated[tuple[Optional[str], Optional[str]], Depends(get_auth_context)],
) -> dict[str, Any]:
    return list_farms_sync(auth=auth)


@app.get("/api/farms/{farm_id}", response_model=FarmMemory)
async def get_farm(
    farm_id: str,
    auth: Annotated[tuple[Optional[str], Optional[str]], Depends(get_auth_context)],
) -> FarmMemory:
    user_id, access_token = auth
    return memory_store.get_or_create_farm(farm_id, user_id=user_id, access_token=access_token)


@app.post("/api/farms/{farm_id}/sync", response_model=FarmMemory)
async def sync_farm_memory(
    farm_id: str,
    payload: FarmMemory,
    auth: Annotated[tuple[Optional[str], Optional[str]], Depends(get_auth_context)],
) -> FarmMemory:
    """Restore or merge a device-local FarmMemory snapshot into the active backend store."""
    user_id, access_token = auth
    if hasattr(memory_store, "sync_farm_memory"):
        return memory_store.sync_farm_memory(farm_id=farm_id, incoming=payload)
    return memory_store.get_or_create_farm(farm_id, user_id=user_id, access_token=access_token)


def update_farm_location_sync(
    farm_id: str,
    payload: LocationUpdateRequest,
    auth: tuple[Optional[str], Optional[str]] = (None, None),
) -> FarmMemory:
    user_id, access_token = auth
    return memory_store.update_location(
        farm_id=farm_id,
        locality=payload.locality,
        latitude=payload.latitude,
        longitude=payload.longitude,
        user_id=user_id,
        access_token=access_token,
    )


@app.post("/api/farms/{farm_id}/location", response_model=FarmMemory)
async def update_farm_location(
    farm_id: str,
    payload: LocationUpdateRequest,
    auth: Annotated[tuple[Optional[str], Optional[str]], Depends(get_auth_context)],
) -> FarmMemory:
    return update_farm_location_sync(farm_id, payload, auth=auth)


def _allow_nasa_network() -> bool:
    return os.getenv("NASA_POWER_ALLOW_NETWORK", "true").lower() == "true"


def export_farm_memory_sync(
    farm_id: str,
    auth: tuple[Optional[str], Optional[str]] = (None, None),
    allow_network: Optional[bool] = None,
) -> dict[str, Any]:
    user_id, access_token = auth
    farm = memory_store.get_or_create_farm(farm_id, user_id=user_id, access_token=access_token)
    lat = farm.location.latitude or 5.647
    lon = farm.location.longitude or 100.487
    use_net = _allow_nasa_network() if allow_network is None else allow_network
    climate = climate_service.get_summary(lat, lon, allow_network=use_net)
    geotanih = load_geotanih_context(farm.location.locality or "Sungai Petani, Kedah")
    return {
        "farm_memory": farm.model_dump(mode="json"),
        "geotanih_context": geotanih,
        "climate_summary": climate.model_dump(mode="json"),
    }


@app.get("/api/farms/{farm_id}/export")
async def export_farm_memory(
    farm_id: str,
    auth: Annotated[tuple[Optional[str], Optional[str]], Depends(get_auth_context)],
) -> dict[str, Any]:
    return export_farm_memory_sync(farm_id, auth=auth)


@app.get("/api/farms/{farm_id}/check-in")
async def get_farm_checkin(
    farm_id: str,
    auth: Annotated[tuple[Optional[str], Optional[str]], Depends(get_auth_context)],
    language: LanguageCode = LanguageCode.MS,
) -> dict[str, object]:
    """Return one optional, context-aware check-in prompt based on saved FarmMemory."""
    user_id, access_token = auth
    farm = memory_store.get_or_create_farm(farm_id, user_id=user_id, access_token=access_token)
    checkin = libraries.get_optional_checkin(farm, language=language)
    return {"farm_id": farm.farm_id, "checkin": checkin}


def compare_farm_rotations_sync(
    payload: CompareRequest,
    auth: tuple[Optional[str], Optional[str]] = (None, None),
    allow_network: Optional[bool] = None,
) -> dict[str, Any]:
    user_id, access_token = auth
    farm = memory_store.get_or_create_farm(payload.farm_id, user_id=user_id, access_token=access_token)
    lat = farm.location.latitude or 5.647
    lon = farm.location.longitude or 100.487
    use_net = _allow_nasa_network() if allow_network is None else allow_network
    climate = climate_service.get_summary(lat, lon, scenario=payload.scenario, allow_network=use_net)
    result = compare_rotations(
        memory=farm,
        libraries=libraries,
        climate=climate,
        candidate_crop_names=payload.candidate_crops,
        scenario=payload.scenario,
    )
    memory_store.save_rotation_comparison(
        farm_id=payload.farm_id,
        result=result,
        user_id=user_id,
        access_token=access_token,
    )
    return result


@app.post("/api/compare")
async def compare_farm_rotations(
    payload: CompareRequest,
    auth: Annotated[tuple[Optional[str], Optional[str]], Depends(get_auth_context)],
) -> dict[str, Any]:
    return compare_farm_rotations_sync(payload, auth=auth)


@app.delete("/api/farms/{farm_id}")
async def delete_farm(
    farm_id: str,
    auth: Annotated[tuple[Optional[str], Optional[str]], Depends(get_auth_context)],
) -> dict[str, bool]:
    user_id, access_token = auth
    return {"deleted": memory_store.delete_farm(farm_id, user_id=user_id, access_token=access_token)}


@app.post("/api/voice/turn", response_model=VoiceTurnResponse)
async def voice_turn(
    audio: Annotated[UploadFile, File()],
    farm_id: Annotated[str, Form()],
    session_id: Annotated[str, Form()],
    auth: Annotated[tuple[Optional[str], Optional[str]], Depends(get_auth_context)],
    language: Annotated[LanguageCode, Form()] = LanguageCode.MS,
    current_question_id: Annotated[Optional[str], Form()] = None,
    include_tts: Annotated[bool, Form()] = True,
) -> VoiceTurnResponse:
    """Accepts one spoken answer, transcribes in-memory, and discards raw audio immediately."""
    user_id, access_token = auth
    voice = get_voice_service()
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio upload.")

    try:
        transcript = await voice.transcribe_audio(
            audio_bytes=audio_bytes,
            filename=audio.filename or "audio.webm",
            content_type=audio.content_type or "audio/webm",
            language=language,
        )
    finally:
        del audio_bytes
        await audio.close()

    return await _process_utterance(
        transcript=transcript,
        farm_id=farm_id,
        session_id=session_id,
        language=language,
        current_question_id=current_question_id,
        include_tts=include_tts,
        user_id=user_id,
        access_token=access_token,
    )


@app.post("/api/voice/chat", response_model=VoiceTurnResponse)
async def voice_chat(
    payload: VoiceChatRequest,
    auth: Annotated[tuple[Optional[str], Optional[str]], Depends(get_auth_context)],
    include_tts: bool = False,
) -> VoiceTurnResponse:
    """Text fallback for the same multilingual interview and Q&A pipeline."""
    user_id, access_token = auth
    return await _process_utterance(
        transcript=payload.text,
        farm_id=payload.farm_id,
        session_id=payload.session_id,
        language=payload.language,
        current_question_id=payload.current_question_id,
        include_tts=include_tts,
        user_id=user_id,
        access_token=access_token,
    )


@app.post("/api/voice/confirm")
async def confirm_fact(
    payload: VoiceConfirmRequest,
    auth: Annotated[tuple[Optional[str], Optional[str]], Depends(get_auth_context)],
) -> dict[str, object]:
    """Save a farmer-confirmed fact to FarmMemory and return the next interview question."""
    user_id, access_token = auth
    pending = memory_store.pop_pending(payload.session_id, payload.confirmation_id)
    if pending is None:
        raise HTTPException(status_code=404, detail="Pending confirmation not found or already handled.")

    farm = (
        memory_store.apply_confirmed_fact(
            farm_id=payload.farm_id,
            target_field=pending.target_field,
            value=pending.proposed_value,
            user_id=user_id,
            access_token=access_token,
        )
        if payload.accepted
        else memory_store.get_or_create_farm(payload.farm_id, user_id=user_id, access_token=access_token)
    )

    next_q = libraries.get_next_question(farm, geotanih_flags=_geotanih_flags_for(farm))
    return {
        "saved": payload.accepted,
        "farm_memory": farm,
        "next_question": next_q,
    }


@app.websocket("/ws/voice/{farm_id}/{session_id}")
async def voice_realtime_ws(
    websocket: WebSocket,
    farm_id: str,
    session_id: str,
    language: LanguageCode = LanguageCode.MS,
    token: Optional[str] = None,
    noise_mode: str = "strict",
) -> None:
    """Live bidirectional audio/text WebSocket backed by gpt-realtime-2.1-mini."""
    if not os.getenv("OPENAI_API_KEY"):
        await websocket.close(code=1011, reason="OPENAI_API_KEY is not configured.")
        return

    user_id: Optional[str] = None
    access_token: Optional[str] = None
    if isinstance(memory_store, SupabaseMemoryStore):
        if not token:
            await websocket.close(code=1008, reason="Missing Supabase token query parameter.")
            return
        try:
            user_id = memory_store.verify_user(token)
            access_token = token
        except HTTPException:
            await websocket.close(code=1008, reason="Invalid or expired Supabase token.")
            return

    realtime = get_realtime_service()
    await realtime.handle_websocket(
        websocket=websocket,
        farm_id=farm_id,
        session_id=session_id,
        language=language,
        libraries=libraries,
        memory_store=memory_store,
        user_id=user_id,
        access_token=access_token,
        noise_mode=noise_mode,
    )
