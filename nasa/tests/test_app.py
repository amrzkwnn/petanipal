import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_memory_store_skip_advances_list_and_location(tmp_path):
    from services.library_store import LibraryStore
    from services.memory_store import MemoryStore

    libs = LibraryStore(Path("nasa/data"))
    store = MemoryStore(base_dir=tmp_path)
    farms = store.list_farms()
    assert farms[0]["farm_id"] == "farm_001"

    store.update_location("farm_001", "Sungai Petani, Kedah", 5.647, 100.487)
    store.apply_confirmed_fact("farm_001", "crop_history", {"crop_id": "jagung_manis", "raw_crop_name": "Jagung"})
    store.apply_confirmed_fact("farm_001", "irrigation_availability", "skip")
    store.apply_confirmed_fact("farm_001", "soil.flooded_last_season", "skip")

    farm = store.get_or_create_farm("farm_001")
    assert farm.location.latitude == 5.647
    assert farm.irrigation_availability.value.value == "unknown"
    assert farm.soil.flooded_last_season.value == "unknown"
    next_q = libs.get_next_question(farm)
    assert next_q is not None and next_q.question_id != "irrigation_availability"


def test_geotanih_market_and_chilli_crop_profile():
    from schemas.farm_memory import EvidenceLabel
    from services.geotanih_store import load_geotanih_context, load_market_context
    from services.library_store import LibraryStore

    libs = LibraryStore(Path("nasa/data"))
    chilli = libs.match_crop_name("chilli") or libs.match_crop_name("cili")
    assert chilli is not None and chilli.crop_id == "chilli_open_field"

    geo = load_geotanih_context("Sungai Petani, Kedah", allow_live=False)
    assert geo["evidence_label"] == EvidenceLabel.ESTIMATED_FROM_MAP
    assert "geotanih_drainage_limitation" in geo["flags"]

    geo_kp = load_geotanih_context("Kubang Pasu, Kedah", allow_live=False)
    assert geo_kp["evidence_label"] == EvidenceLabel.ESTIMATED_FROM_MAP
    assert geo_kp["selected_district"] == "Kubang Pasu, Kedah"

    geo_kulim = load_geotanih_context("Kulim, Kedah", allow_live=False)
    assert geo_kulim["evidence_label"] == EvidenceLabel.ESTIMATED_FROM_MAP
    assert geo_kulim["selected_district"] == "Kulim, Kedah"

    geo_unk = load_geotanih_context("Unknown Mukim", allow_live=False)
    assert geo_unk["evidence_label"] == EvidenceLabel.UNKNOWN

    mkt = load_market_context("chilli_open_field")
    assert "not a future-price promise" in mkt["disclaimer_en"].lower()
    mkt_unk = load_market_context("durian")
    assert mkt_unk["trend"] == "unknown"


def test_climate_service_7d_30d_scenarios_and_subwindow_insights(tmp_path):
    from schemas.farm_memory import EvidenceLabel
    from services.climate_service import NasaPowerClimateService, compute_climate_summary

    precip = {}
    tmax = {}
    tmin = {}
    for i in range(1, 31):
        day = f"202603{i:02d}"
        precip[day] = 0.0 if i <= 10 else (28.0 if i >= 26 else 4.0)
        tmax[day] = 35.5 if 12 <= i <= 18 else 31.5
        tmin[day] = 24.0

    summary = compute_climate_summary(
        lat=5.647,
        lon=100.487,
        precip=precip,
        tmax=tmax,
        tmin=tmin,
        scenario="normal",
        duration_days=90,
    )
    assert summary.evidence_label == EvidenceLabel.ESTIMATED_FROM_CLIMATE
    assert summary.rain_7d_mm > 0
    assert summary.rain_30d_mm > summary.rain_7d_mm
    assert summary.dry_spell_count >= 1
    assert summary.planting_window_rain_low is True
    assert summary.heavy_rain_near_harvest is True
    assert summary.hot_days_during_flowering >= 5
    assert len(summary.plain_insights_en) >= 2
    assert len(summary.plain_insights_ms) >= 2

    drier = compute_climate_summary(
        lat=5.647,
        lon=100.487,
        precip=precip,
        tmax=tmax,
        tmin=tmin,
        scenario="drier",
        duration_days=90,
    )
    wetter = compute_climate_summary(
        lat=5.647,
        lon=100.487,
        precip=precip,
        tmax=tmax,
        tmin=tmin,
        scenario="wetter",
        duration_days=90,
    )
    assert drier.rain_30d_mm < summary.rain_30d_mm < wetter.rain_30d_mm

    svc = NasaPowerClimateService(cache_dir=tmp_path)
    offline_summary = svc.get_summary(5.647, 100.487, scenario="normal", duration_days=75, allow_network=False)
    assert offline_summary.rain_30d_mm > 0


def test_rotation_engine_observations_pests_and_unlisted_crop(tmp_path):
    from datetime import datetime, timezone
    from schemas.farm_memory import CropHistoryEntry, EvidenceLabel, FieldObservation, SoilFeel, TrackedValue, WaterloggingDuration
    from services.climate_service import NasaPowerClimateService
    from services.library_store import LibraryStore
    from services.memory_store import MemoryStore
    from services.rotation_engine import compare_rotations

    libs = LibraryStore(Path("nasa/data"))
    store = MemoryStore(base_dir=tmp_path)
    mem = store.get_or_create_farm("farm-rot-1")
    now = datetime.now(timezone.utc)
    mem.crop_history.append(
        CropHistoryEntry(
            season="previous_season",
            crop_id="chilli_open_field",
            raw_crop_name="chilli",
            evidence_label=EvidenceLabel.VERIFIED_BY_FARMER,
            confirmed_at=now,
        )
    )
    mem.soil.texture_feel = TrackedValue(
        value=SoilFeel.STICKY,
        evidence_label=EvidenceLabel.VERIFIED_BY_FARMER,
        confirmed_at=now,
    )
    mem.soil.waterlogging_duration = TrackedValue(
        value=WaterloggingDuration.OVER_TWO_DAYS,
        evidence_label=EvidenceLabel.VERIFIED_BY_FARMER,
        confirmed_at=now,
    )
    mem.field_observations.append(
        FieldObservation(
            zone="North Bed",
            event_type="pest",
            affected_crop="chilli",
            observation="Heavy thrips and anthracnose on chilli in North Bed",
            evidence_label=EvidenceLabel.VERIFIED_BY_FARMER,
            recorded_at=now,
        )
    )
    store._save_farm(mem)

    climate = NasaPowerClimateService(cache_dir=tmp_path).get_summary(
        5.647, 100.487, scenario="wetter", allow_network=False
    )
    result = compare_rotations(
        memory=mem,
        libraries=libs,
        climate=climate,
        candidate_crop_names=["kacang tanah", "chilli", "durian"],
        scenario="wetter",
    )
    assert len(result["options"]) == 3
    by_id = {opt["crop_id"]: opt for opt in result["options"]}
    assert "chilli_open_field" in by_id
    chilli_opt = by_id["chilli_open_field"]
    assert chilli_opt["risk_level"] == "High"
    assert any("Solanaceae" in r or "same crop family" in r.lower() for r in chilli_opt["risks_en"])
    assert any("North Bed" in r or "thrips" in r.lower() for r in chilli_opt["risks_en"])

    durian_opt = by_id["unlisted_durian"]
    assert durian_opt["unlisted"] is True
    assert len(durian_opt["missing_info_en"]) >= 1
    assert "evidence_coverage" in result
    assert "recorded_observations" in result
    assert len(result["recorded_observations"]) == 1
    serialized = str(result).lower()
    assert "plant this crop" not in serialized


def test_offline_router_and_main_endpoints(tmp_path):
    from schemas.farm_memory import LanguageCode
    from schemas.voice import OpenQuestionType, VoiceChatRequest, VoiceConfirmRequest
    from services.library_store import LibraryStore
    from services.memory_store import MemoryStore
    from services.offline_router import route_offline
    from services.rotation_engine import compare_rotations

    libs = LibraryStore(Path("nasa/data"))
    store = MemoryStore(base_dir=tmp_path)
    farm = store.get_or_create_farm("farm_sp_1")
    comp = compare_rotations(farm, libs)

    # 1. Spontaneous event
    r_event = route_offline(
        transcript="Bahagian rendah air bertakung 3 hari lepas hujan",
        language=LanguageCode.MS,
        farm=farm,
        current_question=libs.get_question("q02_waterlogging"),
        libraries=libs,
        comparison_context=comp,
    )
    assert r_event.question_type == OpenQuestionType.SPONTANEOUS_EVENT
    assert r_event.extracted_target_field == "field_observations"
    assert r_event.needs_confirmation is True

    # 2. High-stakes pesticide/chemical referral
    r_high = route_offline(
        transcript="Racun apa dan berapa ml/L nak sembur ulat?",
        language=LanguageCode.MS,
        farm=farm,
        current_question=None,
        libraries=libs,
        comparison_context=comp,
    )
    assert r_high.question_type == OpenQuestionType.HIGH_STAKES_EXPERT_REFERRAL
    assert r_high.needs_confirmation is False
    assert "pegawai pertanian" in r_high.assistant_text.lower() or "doa" in r_high.assistant_text.lower()

    # 3. What-if scenario
    r_whatif = route_offline(
        transcript="What if next season is drier and I only have rain?",
        language=LanguageCode.EN,
        farm=farm,
        current_question=None,
        libraries=libs,
        comparison_context=comp,
    )
    assert r_whatif.question_type == OpenQuestionType.WHAT_IF_SCENARIO
    assert "historical scenario, not a weather forecast" in r_whatif.assistant_text.lower()
    assert len(r_whatif.answer_basis) >= 1

    # 4. Result explanation
    r_why = route_offline(
        transcript="Kenapa kacang tanah sesuai selepas cili?",
        language=LanguageCode.MS,
        farm=farm,
        current_question=None,
        libraries=libs,
        comparison_context=comp,
    )
    assert r_why.question_type == OpenQuestionType.RESULT_EXPLANATION
    assert len(r_why.answer_basis) >= 1

    # 5. Question 8 ("disease" / "penyakit") on q08_previous_crop_issue
    q08 = libs.get_question("q08_previous_crop_issue")
    r_q08 = route_offline(
        transcript="Ada masalah penyakit daun dan kulat musim lepas",
        language=LanguageCode.MS,
        farm=farm,
        current_question=q08,
        libraries=libs,
        comparison_context=comp,
    )
    assert r_q08.question_type == OpenQuestionType.INTERVIEW_ANSWER
    assert r_q08.extracted_value == "disease"
    assert r_q08.needs_confirmation is True

    # 5b. Off-topic guardrail (stays strictly on farming / plot topics)
    r_off = route_offline(
        transcript="Write Python code to predict bitcoin price",
        language=LanguageCode.EN,
        farm=farm,
        current_question=q08,
        libraries=libs,
        comparison_context=comp,
    )
    assert r_off.question_type == OpenQuestionType.OUT_OF_SCOPE
    assert r_off.needs_confirmation is False

    # 6. Verify main.py endpoints (config, farms list, location update, compare, export, check-in)
    import main as main_mod
    main_mod.memory_store = store

    cfg = main_mod.get_public_config_sync()
    assert "supabase_enabled" in cfg

    farms_resp = main_mod.list_farms_sync(auth=(None, None))
    assert any(f["farm_id"] == "farm_sp_1" for f in farms_resp["farms"])

    loc_resp = main_mod.update_farm_location_sync(
        "farm_sp_1",
        main_mod.LocationUpdateRequest(locality="Sungai Petani, Kedah", latitude=5.647, longitude=100.487),
        auth=(None, None),
    )
    assert loc_resp.location.latitude == 5.647

    cmp_resp = main_mod.compare_farm_rotations_sync(
        main_mod.CompareRequest(
            farm_id="farm_sp_1",
            candidate_crops=["kacang tanah", "chilli", "jagung manis"],
            scenario="normal",
        ),
        auth=(None, None),
        allow_network=False,
    )
    assert len(cmp_resp["options"]) == 3

    exp_resp = main_mod.export_farm_memory_sync("farm_sp_1", auth=(None, None), allow_network=False)
    assert exp_resp["farm_memory"]["farm_id"] == "farm_sp_1"
    assert "geotanih_context" in exp_resp


def test_stitch_frontend_wiring_and_safety():
    html_path = Path("nasa/static/index.html")
    assert html_path.exists(), "nasa/static/index.html must exist"
    html = html_path.read_text(encoding="utf-8")

    # 1. Exact Stitch design tokens, typography & claymorphism classes
    assert "Space Grotesk" in html
    assert "Material+Symbols+Outlined" in html
    assert "#f5eee7" in html.lower()
    assert "#fbf6f2" in html.lower()
    assert "clay-card" in html
    assert "clay-nav" in html
    assert "earth-globe" in html
    assert "spinLand" in html
    assert "spinClouds" in html
    assert "ytVideoIframe" in html

    # 2. All 4 Stitch screens & required text markers
    assert "PetaniPal" in html
    assert "Your Farms" in html
    assert "YOU SAID" not in html
    assert "PAL SAYS" in html
    assert "Hold to speak" in html
    assert "Rotation detail" in html
    assert "Before you decide" in html
    assert "Why this result?" in html
    assert "speechSynthesis" in html

    # 3. Top segmented navigation tabs strictly Pal | Records | Settings
    assert "Pal" in html
    assert "Records" in html
    assert "Settings" in html

    # 4. API & WebSocket wiring
    for endpoint in [
        "/api/config",
        "/api/farms",
        "/api/voice/turn",
        "/api/voice/chat",
        "/api/voice/confirm",
        "/api/compare",
        "/check-in",
        "/export",
        "/ws/voice/",
    ]:
        assert endpoint in html, f"Missing endpoint {endpoint} in index.html"

    # 5. Safety: never command 'Plant this crop' and include mandatory privacy disclosures + WS handler + Records screen + Stitch assets
    assert "plant this crop" not in html.lower()
    assert "We do not keep your voice. We only save facts you confirm." in html
    assert "OpenAI" in html
    assert "pending_confirmation" in html
    assert "transcript_delta" in html
    assert "screen-records" in html
    assert "escapeHtml" in html
    assert "kedah-district-map" in html
    assert "selectDistrictFromMap" in html
    assert "dist-kubang_pasu" in html
    assert "dist-kuala_muda" in html
    assert "rotation_updated" in html
    assert "refresh_context" in html
    assert "createBiquadFilter" in html
    assert "noiseFloorRms" in html
    assert "update_audio_filter" in html
    assert "setVoiceFilterMode" in html
    assert "liveEchoTailUntil" in html
    assert Path("nasa/stitch_design/design-theme.json").exists()


def test_realtime_instructions_include_nasa_climate_and_rotation_context(tmp_path):
    from schemas import LanguageCode
    from services.climate_service import NasaPowerClimateService
    from services.library_store import LibraryStore
    from services.memory_store import MemoryStore
    from services.realtime_voice import OpenAIRealtimeService

    libs = LibraryStore(Path("nasa/data"))
    mem = MemoryStore(storage_dir=tmp_path)
    rt = OpenAIRealtimeService(climate_service=NasaPowerClimateService(cache_dir=Path("nasa/storage/climate_cache")))
    rt_text = rt._build_instructions(
        language=LanguageCode.MS,
        libraries=libs,
        memory_store=mem,
        farm_id="farm_sp_1",
        allow_network=False,
    )
    assert "LIVE NASA POWER & PLOT SNAPSHOT" in rt_text
    assert "NASA POWER Climate Summary" in rt_text
    assert "get_nasa_climate_and_rotation" in rt_text
    assert "DOMAIN LOCK" in rt_text
    assert "NEVER GO OFF-TOPIC" in rt_text
    assert "NO RAW STATISTICS" in rt_text
    assert "NEVER SPEAK RAW NUMBERS OR STATS" in rt_text
    assert "NEVER start with filler" in rt_text

    import re
    summary = rt.climate_service.get_summary(5.647, 100.487, scenario="normal", allow_network=False)
    joined_insights = " ".join(summary.plain_insights_en + summary.plain_insights_ms)
    assert not re.search(r"\d+\s*mm\b", joined_insights, re.IGNORECASE)
    assert not re.search(r"\b\d+(?:\.\d+)?\s*°?c\b", joined_insights, re.IGNORECASE)
    assert "nasa power" not in joined_insights.lower()

    from services.rotation_engine import compare_rotations
    farm = mem.get_or_create_farm("farm_sp_1")
    comp = compare_rotations(
        memory=farm,
        libraries=libs,
        climate=summary,
        candidate_crop_names=["chilli", "okra"],
        scenario="normal",
    )
    for opt in comp["options"]:
        text_blob = " ".join(
            opt["climate_water_fit_en"]
            + opt["climate_water_fit_ms"]
            + opt["soil_rotation_benefit_en"]
            + opt["soil_rotation_benefit_ms"]
            + [opt["summary_sentence_en"], opt["summary_sentence_ms"]]
        )
        assert not re.search(r"\d+\s*mm\b", text_blob, re.IGNORECASE)
        assert "nasa power" not in text_blob.lower()
        assert "solanaceae" not in text_blob.lower()

    from services.realtime_voice import _RealtimeResponseBuffer, _audio_input_config

    strict_cfg = _audio_input_config(LanguageCode.MS, "strict")
    assert strict_cfg["noise_reduction"]["type"] == "near_field"
    assert strict_cfg["noise_reduction"]["strength"] == 1.0
    assert strict_cfg["turn_detection"]["threshold"] == 0.68
    assert strict_cfg["turn_detection"]["interrupt_response"] is False

    bal_cfg = _audio_input_config(LanguageCode.EN, "balanced")
    assert bal_cfg["noise_reduction"]["type"] == "far_field"
    assert bal_cfg["turn_detection"]["threshold"] == 0.55
    assert bal_cfg["turn_detection"]["interrupt_response"] is False

    import base64

    buf = _RealtimeResponseBuffer()
    buf.add_transcript("Let's see...")
    buf.add_audio(base64.b64encode(b"\x01\x02").decode("ascii"))
    buf.mark_function_call()
    t1, a1, done1 = buf.consume_ready()
    assert t1 == "" and a1 == "" and done1 is False

    buf.add_transcript("Kacang tanah ")
    buf.add_transcript("sesuai untuk petak ini.")
    buf.add_audio(base64.b64encode(b"\x01\x02").decode("ascii"))
    buf.add_audio(base64.b64encode(b"\x03\x04").decode("ascii"))
    t2, a2, done2 = buf.consume_ready()
    assert t2 == "Kacang tanah sesuai untuk petak ini."
    assert base64.b64decode(a2) == b"\x01\x02\x03\x04"
    assert done2 is True
    assert Path("nasa/stitch_design/01-farmpal-entrance-login.html").exists()
    assert Path("nasa/stitch_design/02-pal-farm-selection.html").exists()
    assert Path("nasa/stitch_design/03-pal-answer-confirm.html").exists()
    assert Path("nasa/stitch_design/04-pal-rotation-detail.html").exists()





