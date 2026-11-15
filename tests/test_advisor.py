"""Unit and API tests for Farm Memory crop-rotation decision support."""

from __future__ import annotations

import importlib

from nasa_power.advisor.data_fetcher import DailyClimateSummary, compute_climate_summary
from nasa_power.advisor.engine import compare_rotations
from nasa_power.advisor.farm_memory import FarmMemoryRecord, FarmMemoryStore


def _make_daily_payload() -> dict[str, dict[str, float]]:
    dates = [f"202401{d:02d}" for d in range(1, 32)] + [f"202402{d:02d}" for d in range(1, 30)] + [f"202403{d:02d}" for d in range(1, 32)]
    return {
        "PRECTOTCORR": {d: (0.0 if i < 15 else (35.0 if i == 20 else 5.0)) for i, d in enumerate(dates)},
        "T2M": {d: 28.0 for d in dates},
        "T2M_MAX": {d: (35.5 if i < 5 else 31.0) for i, d in enumerate(dates)},
        "T2M_MIN": {d: 24.0 for d in dates},
        "RH2M": {d: 82.0 for d in dates},
        "ALLSKY_SFC_SW_DWN": {d: 18.0 for d in dates},
        "GWETTOP": {d: 0.82 for d in dates},
        "GWETROOT": {d: 0.84 for d in dates},
    }


def test_compute_climate_summary_daily_features() -> None:
    summary = compute_climate_summary(
        daily_params=_make_daily_payload(),
        latitude=6.0704,
        longitude=100.3557,
        planting_month=1,
    )
    assert summary.longest_dry_spell_days == 15
    assert summary.heavy_rain_days_per_season == 1.0
    assert summary.hot_days_per_season == 5.0
    assert summary.recent_gwettop == 0.82


def test_compare_rotations_flooded_field_and_unknowns() -> None:
    climate = DailyClimateSummary(
        latitude=6.0704,
        longitude=100.3557,
        planting_month=10,
        scenario="heavy_rain_harvest",
        history_years="2022",
        recent_rain_7d_mm=90.0,
        recent_rain_30d_mm=320.0,
        recent_gwettop=0.92,
        recent_gwetroot=0.94,
        mean_monthly_rain_mm=280.0,
        mean_et0_monthly_mm=120.0,
        water_balance_monthly_mm=160.0,
        longest_dry_spell_days=4,
        heavy_rain_days_per_season=5.0,
        hot_days_per_season=2.0,
        high_humidity_days_per_season=25.0,
        mean_t2m=27.5,
        mean_t2m_max=31.0,
        mean_solar_mj=16.5,
        mean_rh2m=87.0,
        mean_gwettop=0.90,
        mean_gwetroot=0.91,
    )
    memory = FarmMemoryRecord(
        last_crop="chilli_open_field",
        waterlogging_duration="more_than_two_days",
        flooded_last_season="yes",
        soil_ph_known="no_test",
    )

    result = compare_rotations(climate=climate, memory=memory)
    assert len(result.rotations) == 3
    assert result.rotations[0]["is_existing"] is True
    assert "recent soil pH test" in result.evidence_coverage["unknown"]

    scores = {r["crop_id"]: r["score"] for r in result.rotations}
    assert scores["paddy_rice"] > scores["chilli_open_field"]


def test_farm_memory_store_crud(tmp_path) -> None:
    store = FarmMemoryStore(base_dir=tmp_path)
    assert store.get("farm_x") is None

    rec = FarmMemoryRecord(farm_id="farm_x", last_crop="paddy_rice", irrigation="always")
    store.save(rec)
    loaded = store.get("farm_x")
    assert loaded is not None
    assert loaded.last_crop == "paddy_rice"

    assert store.delete("farm_x") is True
    assert store.get("farm_x") is None


def test_fastapi_endpoints(monkeypatch, tmp_path) -> None:
    web_app_mod = importlib.import_module("nasa_power.web.app")
    monkeypatch.setattr(web_app_mod, "_store", FarmMemoryStore(base_dir=tmp_path))

    def fake_get_summary(latitude, longitude, planting_month, scenario="historical_average"):
        return compute_climate_summary(_make_daily_payload(), latitude, longitude, planting_month, scenario)

    monkeypatch.setattr(web_app_mod._fetcher, "get_summary", fake_get_summary)

    assert web_app_mod.serve_index().path.name == "index.html"
    assert len(web_app_mod.get_crops()["crops"]) == 5
    assert len(web_app_mod.get_questions()["questions"]) == 10
    assert web_app_mod.get_districts().status_code == 200

    req = web_app_mod.CompareRequest(
        farm_id="farm_test",
        locality="Kota Setar",
        latitude=6.0704,
        longitude=100.3557,
        planting_month=1,
        scenario="historical_average",
        last_crop="paddy_rice",
    )
    data = web_app_mod.compare(req)
    assert len(data["rotations"]) == 3
    assert "answer_basis" in data


def test_context_loaders_known_and_unknown_fallbacks():
    from nasa_power.advisor.context_data import load_geotanih_context, load_market_context

    soil = load_geotanih_context("Kota Setar")
    assert soil["evidence_label"] == "estimated_from_climate_or_map"
    assert soil["drainage_class"] in {"poor", "imperfect", "moderate", "well"}
    assert soil["source_url"] and soil["last_reviewed"]

    missing_soil = load_geotanih_context("Unknown District")
    assert missing_soil["evidence_label"] == "unknown"

    market = load_market_context("chilli_open_field")
    assert market["trend"] in {"rising", "stable", "softening"}
    assert "not a future-price promise" in market["disclaimer_en"].lower()
    assert market["last_updated"]

    missing_market = load_market_context("nonexistent_crop")
    assert missing_market["evidence_label"] == "unknown"


def test_ten_questions_conditional_followup_and_export(tmp_path):
    from nasa_power.advisor.farm_memory import (
        QUESTION_LIBRARY,
        FarmMemoryRecord,
        FarmMemoryStore,
        next_useful_question,
    )
    web_app_mod = importlib.import_module("nasa_power.web.app")

    fields = {q["field"] for q in QUESTION_LIBRARY}
    assert {"field_problems", "trouble_spot", "labour"}.issubset(fields)
    assert len(QUESTION_LIBRARY) == 10

    mem = FarmMemoryRecord(farm_id="farm_t2", last_crop="paddy_rice", flooded_last_season="yes")
    nxt = next_useful_question(
        mem,
        geotanih={"drainage_class": "poor", "evidence_label": "estimated_from_climate_or_map"},
        target_crop={"crop_id": "chilli_open_field", "flood_tolerance": "low"},
    )
    assert nxt is not None and nxt["field"] == "waterlogging_duration"

    orig_store = web_app_mod._store
    web_app_mod._store = FarmMemoryStore(base_dir=tmp_path)
    try:
        web_app_mod.save_farm("farm_t2", mem)
        resp = web_app_mod.export_farm("farm_t2")
        assert resp.status_code == 200
        assert "attachment" in resp.headers.get("content-disposition", "")
    finally:
        web_app_mod._store = orig_store


def test_climate_7d_30d_and_engine_geotanih_market_replay():
    import pandas as pd
    from nasa_power.advisor.data_fetcher import compute_climate_summary
    from nasa_power.advisor.engine import compare_rotations
    from nasa_power.advisor.farm_memory import FarmMemoryRecord

    dates = pd.date_range("2025-01-01", periods=60, freq="D")
    df = pd.DataFrame({
        "date": dates,
        "PRECTOTCORR": [1.0] * 53 + [10.0] * 7,
        "T2M": [27.5] * 60,
        "T2M_MAX": [35.5] * 60,
        "T2M_MIN": [23.5] * 60,
        "RH2M": [80.0] * 60,
        "ALLSKY_SFC_SW_DWN": [18.0] * 60,
        "GWETTOP": [0.55] * 60,
        "GWETROOT": [0.60] * 60,
    })
    summary = compute_climate_summary(df, planting_month=1, latitude=6.07, scenario="dry_planting")
    assert summary.recent_7d_rain_mm == 70.0
    assert summary.recent_30d_rain_mm == 93.0

    mem = FarmMemoryRecord(farm_id="f3", locality="Kota Setar", last_crop="paddy_rice", irrigation="no")
    res = compare_rotations(
        climate=summary,
        memory=mem,
        geotanih={"drainage_class": "poor", "soil_series": "Kangkong", "evidence_label": "estimated_from_climate_or_map"},
    )
    assert "GeoTanih" in res.answer_basis
    assert res.rotations[0]["market_context"]["disclaimer_en"]
    assert res.is_scenario_forecast is False


def test_open_question_router_safety_and_permission_to_save(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from nasa_power.advisor.conversation import classify_farmer_message, handle_farmer_chat
    from nasa_power.advisor.farm_memory import FarmMemoryRecord, FarmMemoryStore

    assert classify_farmer_message("What pesticide should I spray for leaf curl?") == "high_stakes_safety"
    assert classify_farmer_message("What if the rain starts late next month?") == "what_if_scenario"

    store = FarmMemoryStore(base_dir=tmp_path)
    mem = FarmMemoryRecord(farm_id="f4", last_crop="paddy_rice")
    store.save(mem)

    safety = handle_farmer_chat("Which chemical herbicide kills weeds fastest?", mem)
    assert safety["intent"] == "high_stakes_safety"
    assert "officer" in safety["reply"].lower() or "label" in safety["reply"].lower()

    obs = handle_farmer_chat("The lower part of my field always gets wet after rain.", mem)
    assert obs["pending_confirmation"] is not None
    assert obs["pending_confirmation"]["zone"] == "lower area"
    # Must NOT mutate FarmMemoryStore before farmer confirms
    assert store.get("f4").field_observations == []


def test_frontend_contains_chat_export_tts_and_dialog_guards():
    from pathlib import Path

    html = Path("src/nasa_power/web/static/index.html").read_text(encoding="utf-8")
    assert "/api/chat" in html
    assert "/export" in html
    assert "speechSynthesis" in html
    assert "dialog.returnValue = ''" in html or 'dialog.returnValue = ""' in html


def test_compare_preserves_ten_question_fields_and_observations(monkeypatch):
    web_app_mod = importlib.import_module("nasa_power.web.app")

    def fake_get_summary(latitude, longitude, planting_month, scenario="historical_average"):
        return compute_climate_summary(_make_daily_payload(), latitude, longitude, planting_month, scenario)

    monkeypatch.setattr(web_app_mod._fetcher, "get_summary", fake_get_summary)

    req = web_app_mod.CompareRequest(
        farm_id="f_high",
        last_crop="paddy_rice",
        irrigation="always",
        waterlogging_duration="same_day",
        flooded_last_season="no",
        soil_feel="in_between_loam",
        soil_ph_known="yes_known",
        field_problems="none",
        trouble_spot="none",
        labour="moderate",
        field_observations=[{"zone": "lower area", "observation": "wet", "source": "verified_by_farmer", "recorded_at": "2026-11-15"}],
    )
    res = web_app_mod.compare(req)
    assert res["evidence_coverage"]["level"] == "High"
    assert res["evidence_coverage"]["unknown"] == []


def test_general_drainage_question_does_not_trigger_observation_prompt():
    from nasa_power.advisor.conversation import handle_farmer_chat
    from nasa_power.advisor.farm_memory import FarmMemoryRecord

    mem = FarmMemoryRecord(farm_id="f_gen")
    res = handle_farmer_chat("How do I improve drainage?", mem)
    assert res["pending_confirmation"] is None


def test_frontend_export_visible_and_clear_memory_resets_all_fields():
    from pathlib import Path

    html = Path("src/nasa_power/web/static/index.html").read_text(encoding="utf-8")
    export_line = next(l for l in html.splitlines() if "btn-export-memory" in l)
    assert "color:#fff" not in export_line
    assert 'field_problems: "unknown"' in html
    assert "field_observations: []" in html
