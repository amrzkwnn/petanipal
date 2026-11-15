# PetaniPal (Farm Memory + Stitch Design) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the complete PetaniPal (`Farm Memory`) application inside `nasa/` by combining the existing FastAPI/Supabase/OpenAI backend with the missing NASA POWER, GeoTanih, FAMA AMI, 3-rotation engine, offline fallback, and a strict implementation of the 4-screen Stitch `PetaniPal App Design` fulfilling every requirement in `Development_Plan/project_updated`.

**Architecture:** The backend in `nasa/main.py` serves both the single-page Stitch frontend (`nasa/static/index.html`) and JSON/WebSocket APIs backed by Supabase (`SupabaseMemoryStore`) or local JSON (`MemoryStore`). Deterministic backend services compute NASA POWER daily agroclimate metrics (including planting/flowering/harvest sub-window distribution), GeoTanih soil context + interview trigger flags, FAMA AMI market context, and 3-rotation comparisons, while OpenAI (or `offline_router.py` when `OPENAI_API_KEY` is unset) handles EN/MS voice/text understanding, grounded open-question answers (`result_explanation`, `what_if_scenario`), and farmer confirmation flows. The frontend renders only the 4 Stitch screens (`01` Login/Entrance, `02` Farm Selection, `03` Answer & Confirm + Earth Voice Hub, `04` Rotation Detail with Cards 1–6) plus minimal `Records` and `Settings` views inside the top nav (`Pal | Records | Settings`).

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, OpenAI SDK, Supabase Python & JS (`@supabase/supabase-js` v2), Pandas, Requests/HTTPX, Tailwind CSS + Claymorphism CSS (`Space Grotesk`, `Lexend`, `Material Symbols Outlined`), `pytest`.

**Spec:**
- Product spec: `Development_Plan/project_updated` & `nasa/project_new`
- GeoTanih adapter spec: `nasa/geotanih.md`
- Supabase integration spec: `nasa/SUPABASE_SETUP.md` & `nasa/supabase/schema.sql`
- Stitch design reference: `C:\Users\Amir\.gemini\antigravity-cli\brain\20f57b99-b594-407f-a89d-93e3bdddf1bd\scratch\stitch_design\` (`design-theme.json`, `01-farmpal-entrance-login.html`, `02-pal-farm-selection.html`, `03-pal-answer-confirm.html`, `04-pal-rotation-detail.html`)

## Global Constraints

- One named Malaysian farming locality (`Sungai Petani, Kedah`) with locally reviewed crops (`nasa/data/crops.json`, including `chilli_open_field` per `project_updated:235-250` and Stitch Screens 3–4) and 10 plain-language questions (`nasa/data/question_library.json`).
- Three rotations per comparison: 1 existing rotation plus 2 alternatives (`compare_rotations`).
- Bilingual `en` and `ms` (everyday spoken Malaysian English / Bahasa Melayu); never ask farmers technical terms like `"irrigation reliability"`, `"drainage class"`, or `"soil texture"`.
- `"I do not know"` / `"skip"` are valid answers normalized to `"unknown"`, never guessed or treated as a negative condition.
- Three evidence labels only: `verified_by_farmer`, `estimated_from_map` / `estimated_from_climate` (UI: `"Estimated from map or climate data"`), and `unknown`.
- Never say `"Plant this crop"` or promise guaranteed yields or future market prices.
- Never store raw voice audio buffers, URLs, waveforms, or voiceprints (`PendingConfirmation` stays in memory until `POST /api/voice/confirm` with `accepted=True`), and disclose when audio is sent to OpenAI for speech-to-text transcription (`project_updated:405-412`).
- Never expose `OPENAI_API_KEY` or `SUPABASE_SERVICE_ROLE_KEY` to the frontend; only public `SUPABASE_URL` and anon `SUPABASE_KEY` may be shared with the client.
- Anchor all `nasa/` file reads/writes to `BASE_DIR = Path(__file__).resolve().parent` so running via `uv run uvicorn --app-dir nasa main:app` works from any CWD.
- Strictly match the pulled Stitch `PetaniPal App Design` (`max-w-[480px]` Claymorphism mobile shell, `#f5eee7`/`#fbf6f2`/`#1b4d3e`/`#003629`, top `Pal | Records | Settings` pill nav, spinning Earth `"Hold to speak"` button); do not add unrequested maps, charts, or extra dashboards.

## Review Focus

- **CropProfile attribute shape on pest observations:** `CropProfile` uses `names: dict[str, list[str]]` (not `.name_en`/`.name_ms`); rotation scoring must match `affected_crop` against `crop_id` and `crop.names` values without raising `AttributeError` (verified in Task 4).
- **Grounded Open Questions & GeoTanih Trigger Flags:** When a farmer asks `"Why is this option risky?"` (`result_explanation`) or `"What if the rain starts late?"` (`what_if_scenario`), `_process_utterance` must supply computed NASA POWER + GeoTanih + 3-rotation context and state that a what-if is a historical scenario, not a weather forecast; GeoTanih limitations must pass `geotanih_flags` to `libraries.get_next_question(farm, geotanih_flags)` (verified in Task 2 & Task 5).
- **Working-directory independence & Supabase/local parity:** Both `MemoryStore` and `SupabaseMemoryStore` must support `list_farms`, `update_location`, `export`, and `"skip"` -> `"unknown"` normalization without crashing when Supabase env vars are absent (verified in Task 1 & Task 5).
- **Check-in & live WebSocket confirmation wiring in UI:** `GET /api/farms/{farm_id}/check-in` returns `{"farm_id": ..., "checkin": {"prompt": ...}}` (`data.checkin?.prompt`) and live WS emits `{"type": "pending_confirmation", "data": ...}`; both must trigger the UI confirmation/banner state (verified in Task 6).
- **Safe HTML rendering & `<dialog>` dismissal guard:** Rotation/observation strings interpolated into the DOM must use `textContent` / safe DOM builders (no unescaped `innerHTML`), and `#confirm-dialog` must reset `dialog.returnValue = ""` before `showModal()` so `Esc` cannot submit stale `"confirm"` (verified in Task 6).

---

### Task 1: Anchor Store Paths, `"skip"` Progression,GeoTanih Question Flags, Farm List/Location, and Supabase Parity

**Files:**
- Modify: `nasa/services/memory_store.py`
- Modify: `nasa/services/supabase_memory_store.py`
- Modify: `nasa/services/library_store.py`
- Test: `nasa/tests/test_app.py` (create test file)

**Interfaces:**
- Produces on `MemoryStore` and `SupabaseMemoryStore`:
  - `MemoryStore(storage_dir: Path | str | None = None, *, base_dir: Path | str | None = None)`
  - `list_farms(self, user_id: str | None = None, access_token: str | None = None) -> list[dict[str, Any]]`
  - `update_location(self, farm_id: str, locality: str, latitude: float | None, longitude: float | None, user_id: str | None = None, access_token: str | None = None) -> FarmMemory`
  - `save_rotation_comparison(self, farm_id: str, result: dict[str, Any], user_id: str | None = None, access_token: str | None = None) -> None`
- Produces on `LibraryStore`:
  - `_is_answered(farm: FarmMemory, target_field: str) -> bool` treats any field with `confirmed_at is not None` (including `"unknown"`) as answered so `"skip"` advances `get_next_question`.
  - `get_next_question(self, farm: FarmMemory, geotanih_flags: Optional[set[str]] = None) -> Optional[QuestionItem]` also automatically adds `"crop_flood_sensitive"` when the farmer's last crop in `farm.crop_history` has `flood_tolerance == ToleranceLevel.LOW`.

- [ ] **Step 1: Write failing tests in `nasa/tests/test_app.py`**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest nasa/tests/test_app.py::test_memory_store_skip_advances_list_and_location -v`
Expected: FAIL (`TypeError: MemoryStore.__init__() got an unexpected keyword argument 'base_dir'`).

- [ ] **Step 3: Implement `MemoryStore`, `SupabaseMemoryStore`, and `LibraryStore` updates**

1. In `nasa/services/memory_store.py`:
   - Accept `(storage_dir: Path | str | None = None, *, base_dir: Path | str | None = None)` defaulting to `Path(__file__).resolve().parents[1] / "data" / "farm_memories"`.
   - Normalize `raw_val = "unknown" if value in (None, "unknown", "skip") else str(value)` across all `TrackedValue` fields (including `soil.flooded_last_season` and `soil.trouble_spot`).
   - Implement `list_farms(...)`, `update_location(...)`, and no-op `save_rotation_comparison(...)`.
2. In `nasa/services/supabase_memory_store.py`:
   - Normalize `raw_val = "unknown" if value in (None, "unknown", "skip") else str(value)` in `apply_confirmed_fact`.
   - Implement `list_farms(user_id, access_token)` querying `public.farms` (inserting a default `"My Farm"` row if empty), `update_location(...)` updating `locality`, `latitude`, `longitude`, and `save_rotation_comparison(...)` inserting into `public.rotation_comparisons` (`farm_id`, `user_id`, `options`, `answer_basis`, `missing_info`) per `nasa/SUPABASE_SETUP.md`.
3. In `nasa/services/library_store.py`:
   - Default `data_dir` to `Path(__file__).resolve().parents[1] / "data"`.
   - In `get_next_question`, check if the last `crop_history` entry's `crop_id` resolves to a crop with `flood_tolerance == ToleranceLevel.LOW` and add `"crop_flood_sensitive"` to `flags`.
   - Update `_is_answered` to return `True` when `getattr(obj, "confirmed_at", None) is not None`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest nasa/tests/test_app.py::test_memory_store_skip_advances_list_and_location -v`
Expected: PASS

---

### Task 2: Local Reference Data (`crops.json`, `geotanih_kedah.json`, `market_prices.json`) & Data Loaders (`geotanih_store.py`)

**Files:**
- Modify: `nasa/data/crops.json` (add `chilli_open_field` per `project_updated:235-250` & Stitch Screens 3–4)
- Create: `nasa/data/geotanih_kedah.json`
- Create: `nasa/data/market_prices.json`
- Create: `nasa/services/geotanih_store.py`
- Modify: `nasa/services/__init__.py`
- Test: `nasa/tests/test_app.py`

**Interfaces:**
- Produces in `nasa/services/geotanih_store.py`:
  - `load_geotanih_context(locality: str, latitude: float | None = None, longitude: float | None = None, allow_live: bool = False, cache_dir: Path | None = None) -> dict[str, Any]`
    Returns `{"locality", "soil_series", "texture", "drainage_class", "slope_limitation", "flags": list[str], "source_name", "source_url", "retrieved_at", "evidence_label"}` where `flags` includes `"geotanih_drainage_limitation"`, `"geotanih_texture_limitation"`, or `"geotanih_slope_limitation"` when mapped limitations exist (`project_updated:121-127`).
  - `load_market_context(crop_id: str) -> dict[str, Any]`
    Returns `{"crop_id", "trend", "price_band_rm_per_kg", "note_en", "note_ms", "last_updated", "source_name", "source_url", "disclaimer_en", "disclaimer_ms", "evidence_label"}`.

- [ ] **Step 1: Write the failing test in `nasa/tests/test_app.py`**

```python
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

    geo_unk = load_geotanih_context("Unknown Mukim", allow_live=False)
    assert geo_unk["evidence_label"] == EvidenceLabel.UNKNOWN

    mkt = load_market_context("chilli_open_field")
    assert "not a future-price promise" in mkt["disclaimer_en"].lower()
    mkt_unk = load_market_context("durian")
    assert mkt_unk["trend"] == "unknown"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest nasa/tests/test_app.py::test_geotanih_market_and_chilli_crop_profile -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'services.geotanih_store'`).

- [ ] **Step 3: Add `chilli_open_field` to `crops.json`, create `geotanih_kedah.json`, `market_prices.json`, and `nasa/services/geotanih_store.py`**

- Add `chilli_open_field` (`names`: `{"en": ["chilli", "chili", "open-field chilli"], "ms": ["cili", "cabai", "cili terbuka"]}`, `family: "Solanaceae"`, `duration_days: {"min": 120, "max": 180}`, `water_need: "medium"`, `flood_tolerance: "low"`, `heat_tolerance: "medium"`, `nitrogen_effect: "high_demand"`) to `nasa/data/crops.json`.
- Create `nasa/data/geotanih_kedah.json` (dated Option A seed for `Sungai Petani, Kedah` / `Kuala Muda` with `flags`) and `nasa/data/market_prices.json` (FAMA AMI snapshots + disclaimers for all crops in `crops.json`).
- Implement `load_geotanih_context` (with Option B ArcGIS `SM_SCSC_3/MapServer/0/query` + disk cache when `allow_live=True`, falling back to Option A seed or `unknown`) and `load_market_context`. Export both from `nasa/services/__init__.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest nasa/tests/test_app.py::test_geotanih_market_and_chilli_crop_profile -v`
Expected: PASS

---

### Task 3: NASA POWER Daily Climate Service with Sub-Window Insights (`climate_service.py`)

**Files:**
- Create: `nasa/services/climate_service.py`
- Modify: `nasa/services/__init__.py`
- Modify: `nasa/requirements.txt` (add `pandas`, `requests`, `httpx`)
- Test: `nasa/tests/test_app.py`

**Interfaces:**
- Produces in `nasa/services/climate_service.py`:
  - `@dataclass(frozen=True) class DailyClimateSummary` including:
    - Core metrics: `latitude`, `longitude`, `planting_month`, `scenario`, `history_years`, `recent_rain_7d_mm`, `recent_rain_30d_mm`, `recent_gwettop`, `recent_gwetroot`, `mean_monthly_rain_mm`, `mean_et0_monthly_mm`, `water_balance_monthly_mm`, `longest_dry_spell_days`, `dry_spell_count`, `heavy_rain_days_per_season`, `hot_days_per_season`, `high_humidity_days_per_season`, `mean_t2m`, `mean_t2m_max`, `mean_solar_mj`, `mean_rh2m`, `mean_gwettop`, `mean_gwetroot`.
    - Sub-window distribution flags (`project_updated:299-316`): `planting_window_rain_low: bool`, `heavy_rain_near_harvest: bool`, `hot_days_during_flowering: bool`, `plain_insights_en: list[str]`, `plain_insights_ms: list[str]` (emitting farmer-friendly insights like `"Rain was lower than usual during the planting period"`, `"There were N long dry spells"`, `"Heavy rain was concentrated near harvest"`, `"The hottest days occurred during flowering"`).
  - `compute_climate_summary(df: pd.DataFrame, planting_month: int = 1, scenario: str = "historical_average", latitude: float = 5.647, longitude: float = 100.487) -> DailyClimateSummary`
  - `class NasaPowerClimateService` with disk cache under `nasa/data/cache/nasa_power/`.

- [ ] **Step 1: Write the failing test in `nasa/tests/test_app.py`**

```python
def test_climate_service_7d_30d_scenarios_and_subwindow_insights():
    import pandas as pd
    from services.climate_service import compute_climate_summary

    dates = pd.date_range("2024-01-01", periods=90, freq="D")
    df = pd.DataFrame({
        "date": dates,
        "PRECTOTCORR": [0.2] * 30 + [5.0] * 30 + [45.0] * 30,
        "T2M": [28.0] * 30 + [32.0] * 30 + [27.5] * 30,
        "T2M_MAX": [32.0] * 30 + [36.5] * 30 + [31.0] * 30,
        "T2M_MIN": [24.0] * 90,
        "RH2M": [78.0] * 90,
        "ALLSKY_SFC_SW_DWN": [19.0] * 90,
        "GWETTOP": [0.5] * 90,
        "GWETROOT": [0.55] * 90,
    })
    avg = compute_climate_summary(df, planting_month=1, scenario="historical_average")
    dry = compute_climate_summary(df, planting_month=1, scenario="dry_planting")
    wet = compute_climate_summary(df, planting_month=1, scenario="heavy_rain_harvest")

    assert avg.recent_rain_7d_mm == 315.0
    assert avg.recent_rain_30d_mm == 1350.0
    assert avg.planting_window_rain_low is True
    assert avg.heavy_rain_near_harvest is True
    assert avg.hot_days_during_flowering is True
    assert any("planting" in s.lower() or "harvest" in s.lower() for s in avg.plain_insights_en)
    assert dry.mean_monthly_rain_mm <= wet.mean_monthly_rain_mm
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest nasa/tests/test_app.py::test_climate_service_7d_30d_scenarios_and_subwindow_insights -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'services.climate_service'`).

- [ ] **Step 3: Implement `nasa/services/climate_service.py` and export from `nasa/services/__init__.py`**

Compute daily ET0, dry-spell runs (`PRECTOTCORR < 1.0`), `dry_spell_count` (spells `>= 5` days), heavy rain days (`>= 30.0`), hot days (`T2M_MAX > 34.0`), 7d/30d rainfall, planting/flowering/harvest third-of-window distribution flags + `plain_insights_en/ms`, and scenario selection (`historical_average`, `dry_planting`, `heavy_rain_harvest`, `hot_season`).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest nasa/tests/test_app.py::test_climate_service_7d_30d_scenarios_and_subwindow_insights -v`
Expected: PASS

---

### Task 4: Deterministic 3-Rotation Engine (`rotation_engine.py`) with Field Observation Integration

**Files:**
- Create: `nasa/services/rotation_engine.py`
- Modify: `nasa/services/__init__.py`
- Test: `nasa/tests/test_app.py`

**Interfaces:**
- Produces in `nasa/services/rotation_engine.py`:
  - `compare_rotations(climate: DailyClimateSummary, memory: FarmMemory, crops: list[CropProfile], geotanih: dict[str, Any] | None = None) -> dict[str, Any]`
  - Returns:
    - `locality`, `scenario`, `is_scenario_forecast: False`, `climate_summary`, `geotanih`
    - `evidence_coverage`: `{"level": "High"|"Medium"|"Low", "known": list[str], "unknown": list[str], "before_changing": str}` (`project_updated:169-176`)
    - `missing_info: list[str]`, `answer_basis: list[str]` (`project_updated:204-210`)
    - `recorded_observations`: `[{"zone", "event_type", "observation", "source", "recorded_at"}]` (`project_new:192`)
    - `rotations` (length 3: 1 existing rotation + 2 top alternative rotations), each containing the 5 `project_updated:39-56` sections plus 3-dot ratings for Stitch Screen 4:
      - `crop_id`, `crop_name_en`, `crop_name_ms`, `is_existing`, `rotation_sequence_en`, `rotation_sequence_ms`, `score`
      - `water_fit_level` (`1..3`), `soil_benefit_level` (`1..3`), `risk_level` (`1..3`)
      - `climate_water_fit_en/ms` (incorporating `climate.plain_insights_en/ms`)
      - `soil_rotation_benefit_en/ms` (family, nitrogen-fixing, ground cover/erosion protection)
      - `risks_en/ms` (dry spell, flood, erosion/bare soil, pest-cycle, timing, and confirmed `field_observations`)
      - `missing_info_en/ms` (per-option unknown items like soil pH, dry-season water, market check)
      - `farmer_action_en/ms` (`"Before you decide"` items to verify before planting)
      - `summary_sentence_en/ms` (e.g. `"This option has lower dry-spell exposure based on the historical climate record, but soil pH and buyer availability still need checking."` per `project_updated:60`)
      - `market_context` (from `load_market_context(crop.crop_id)`)

- [ ] **Step 1: Write the failing tests in `nasa/tests/test_app.py`**

```python
def test_rotation_engine_observations_pests_and_unlisted_crop():
    from datetime import datetime, timezone
    import pandas as pd
    from schemas.farm_memory import CropHistoryEntry, FarmMemory, FieldObservation
    from services.climate_service import compute_climate_summary
    from services.library_store import LibraryStore
    from services.rotation_engine import compare_rotations

    dates = pd.date_range("2025-01-01", periods=60, freq="D")
    df = pd.DataFrame({
        "date": dates, "PRECTOTCORR": [2.0] * 60, "T2M": [28.0] * 60,
        "T2M_MAX": [33.0] * 60, "T2M_MIN": [24.0] * 60, "RH2M": [78.0] * 60,
        "ALLSKY_SFC_SW_DWN": [19.0] * 60, "GWETTOP": [0.55] * 60, "GWETROOT": [0.60] * 60,
    })
    climate = compute_climate_summary(df)
    libs = LibraryStore(Path("nasa/data"))
    mem = FarmMemory(
        farm_id="f_rot",
        crop_history=[CropHistoryEntry(season="previous_season", crop_id=None, raw_crop_name="dragonfruit")],
        field_observations=[
            FieldObservation(
                zone="lower area", event_type="flooding", observation="Water stayed 3 days",
                source="farmer-confirmed", recorded_at=datetime(2026, 11, 15, tzinfo=timezone.utc),
            ),
            FieldObservation(
                zone="east plot", event_type="pest", affected_crop="jagung",
                observation="Many insects on maize", source="farmer-confirmed",
                recorded_at=datetime(2026, 11, 15, tzinfo=timezone.utc),
            ),
        ],
    )
    res = compare_rotations(climate=climate, memory=mem, crops=libs.list_crops())
    assert len(res["rotations"]) == 3
    assert len(res["recorded_observations"]) == 2
    assert res["recorded_observations"][0]["source"] == "farmer-confirmed"
    for rot in res["rotations"]:
        assert 1 <= rot["water_fit_level"] <= 3
        assert 1 <= rot["risk_level"] <= 3
        assert "farmer_action_en" in rot and "summary_sentence_en" in rot
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest nasa/tests/test_app.py::test_rotation_engine_observations_pests_and_unlisted_crop -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'services.rotation_engine'`).

- [ ] **Step 3: Implement `nasa/services/rotation_engine.py` and export `compare_rotations`**

Implement `_score_crop` and `compare_rotations` using `crop.names` for pest matching, `climate.plain_insights_en/ms`, bare-soil/ground-cover erosion checks (`crop.ground_cover`), `summary_sentence_en/ms`, `farmer_action_en/ms`, and `recorded_observations`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest nasa/tests/test_app.py::test_rotation_engine_observations_pests_and_unlisted_crop -v`
Expected: PASS

---

### Task 5: Grounded Open-Question & Offline Router (`offline_router.py`) + `nasa/main.py` Endpoints

**Files:**
- Create: `nasa/services/offline_router.py`
- Modify: `nasa/services/openai_voice.py`
- Modify: `nasa/main.py`
- Test: `nasa/tests/test_app.py`

**Interfaces:**
- Produces in `nasa/services/offline_router.py`:
  - `route_offline(transcript: str, language: LanguageCode, farm: FarmMemory, current_question: QuestionItem | None, crops: list[CropProfile], comparison_context: dict[str, Any] | None = None) -> LLMExtractionResult`
  - Handles:
    1. `"skip"` / `"not sure"` / `"tak pasti"` -> `"unknown"`
    2. Interview choices (including Question 8 `disease`/`insects`/`weeds`/`too_much_water`/`too_little_water`, and ambiguous `"chilli"`/`"cili"` open-field confirmation note per `project_updated:230`)
    3. Spontaneous field events (`question_type=OpenQuestionType.SPONTANEOUS_EVENT`, `extracted_target_field="field_observations"`, `observation_zone`, `observation_event_type`, `observation_affected_crop`, `observation_timing_or_duration`, `needs_confirmation=True`)
    4. `RESULT_EXPLANATION` (`"Why is this option risky?"`, `"Can I grow chilli after maize?"`) grounded in `comparison_context` (`rotations`, `answer_basis`, `missing_info`)
    5. `WHAT_IF_SCENARIO` (`"What if the rain starts late?"` -> `dry_planting`; `"heavy rain"` -> `heavy_rain_harvest`; `"hot"` -> `hot_season`), grounded in `comparison_context` and explicitly stating `"This is a historical scenario, not a weather forecast."` (`project_updated:137`)
    6. `HIGH_STAKES_EXPERT_REFERRAL` for pesticide/chemical/diagnosis queries (`project_updated:140`)
    7. General farming questions (`GENERAL_FARMING`) without saving to `FarmMemory` (`project_updated:153`).
- Updates `OpenAIVoiceService.analyze_and_respond` in `nasa/services/openai_voice.py` to accept optional `comparison_context: dict[str, Any] | None = None` in `context_payload` (`project_updated:202`).
- Updates `nasa/main.py`:
  - Passes `geotanih_flags=set(load_geotanih_context(farm.location.locality)["flags"])` into `libraries.get_next_question(farm, geotanih_flags=...)`.
  - Computes `comparison_context` in `_process_utterance` (selecting the matching scenario when a what-if question is asked) and passes it to `voice.analyze_and_respond(...)` or `route_offline(...)`.
  - Adds `GET /`, `GET /api/config`, `GET /api/farms`, `POST /api/farms/{farm_id}/location`, `GET /api/farms/{farm_id}/export`, and `POST /api/compare` while keeping all existing routes and Supabase JWT support intact.

- [ ] **Step 1: Write the failing tests in `nasa/tests/test_app.py`**

Test `route_offline` and `main.py` for:
- spontaneous flooding/pest events (`SPONTANEOUS_EVENT`, `needs_confirmation=True`) and post-confirm `drainage_followup` check-in
- `"What if the rain starts late?"` (`WHAT_IF_SCENARIO`, states `"scenario"`, not forecast, `needs_confirmation=False`)
- `"Why is this option risky?"` / `"Can I grow chilli after maize?"` (`RESULT_EXPLANATION` / `GENERAL_FARMING`, `needs_confirmation=False`)
- high-stakes chemical query (`HIGH_STAKES_EXPERT_REFERRAL`, `needs_confirmation=False`)
- Question 8 `"disease"` choice (`INTERVIEW_ANSWER`, `needs_confirmation=True`)
- `GET /api/farms/{farm_id}/export` and `POST /api/compare`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest nasa/tests/test_app.py -k "offline or compare" -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'services.offline_router'`).

- [ ] **Step 3: Implement `offline_router.py`, update `openai_voice.py`, and update `main.py`**

Implement `route_offline` and wire `_process_utterance` + new routes in `nasa/main.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest nasa/tests/test_app.py -v`
Expected: PASS

---

### Task 6: Stitch `PetaniPal` Frontend (`nasa/static/index.html`) Matching All 4 Screens & `project_updated`

**Files:**
- Create: `nasa/static/index.html`
- Create/Restore reference copies: `nasa/stitch_design/` (`design-theme.json` + 4 HTML screens copied from `scratch/stitch_design/`)
- Test: `nasa/tests/test_app.py`

**Interfaces:**
Consumes backend endpoints:
- `GET /api/config`, `GET /api/crops`, `GET /api/questions`
- `GET /api/farms`, `GET /api/farms/{farm_id}`, `GET /api/farms/{farm_id}/check-in`, `GET /api/farms/{farm_id}/export`, `POST /api/farms/{farm_id}/location`, `DELETE /api/farms/{farm_id}`
- `POST /api/voice/turn`, `POST /api/voice/chat`, `POST /api/voice/confirm`, `WS /ws/voice/{farm_id}/{session_id}`
- `POST /api/compare`

**Strict Stitch Screen & `project_updated` Mapping (Zero Unrequested Widgets):**
1. **Screen 1 (`01-farmpal-entrance-login.html`):** Full-bleed dark entrance with background video, liquid-glass `PetaniPal` login card (`Email`, `Password`, `Sign In`, `Biometric ID` / `"Continue to Farm"`). Uses `@supabase/supabase-js` when `config.storage === "supabase"`, or transitions directly into `Pal` in local mode.
2. **Main App Mobile Shell (`02` / `03` / `04`, `max-w-[480px]`, `#f5eee7`, `.clay-card`, `.clay-nav`, `.clay-pill-btn`, `.clay-green-btn`, `Space Grotesk`):**
   - **Top Floating Segmented Nav:** `Pal` | `Records` | `Settings`.
   - **Context Utility Pills (under nav in `Pal`):** `Farm` | `Details`.
   - **Screen 2 (`Farm` pill -> `Your Farms` from `02-pal-farm-selection.html`):** Lists saved farms from `GET /api/farms` with `Active` badge, swap button, and **Add new farm**.
   - **Screen 3 (`Pal` default -> `YOU SAID` / `PAL SAYS` confirmation card from `03-pal-answer-confirm.html`):**
     - Optional check-in prompt banner (`GET /api/farms/{farm_id}/check-in` reading `data.checkin?.prompt`) + **Skip** button.
     - `YOU SAID` header + **Read** TTS (`speechSynthesis`) button + farmer utterance display + minimal text input bar (`"Tell Farm Memory what happened"` / open question via `POST /api/voice/chat`) + quick-answer pills for the current interview question (`GET /api/questions`).
     - `PAL SAYS` header + assistant reply + explicit **Yes, Save Memory** / **Cancel** confirmation buttons in the `<!-- Confirmation Interactive Buttons -->` slot (plus `<dialog id="confirm-dialog">` resetting `dialog.returnValue = ""` before `showModal()`), wired to `POST /api/voice/confirm`.
   - **Screen 4 (`Details` pill -> `Rotation detail` from `04-pal-rotation-detail.html`):**
     - **Back** button + `Rotation detail` title + 3 rotation selector pills (`Existing` + 2 `Suggested` alternatives from `POST /api/compare`) + **Listen** TTS button + `summary_sentence`.
     - **Card 1: Climate and water fit** (3-dot `Water fit` rating + plain-language climate/water explanation).
     - **Card 2: Soil and rotation benefit** (3-dot `Soil benefit` rating + soil/rotation benefit explanation).
     - **Card 3: Risks** (3-dot `Risk` rating + risk bullets including confirmed `field_observations`).
     - **Card 4: Missing information** (badge rows for unknown fields + evidence labels `Verified by farmer` / `Estimated from map or climate data` / `Unknown`).
     - **Card 5: Before you decide** (`04-pal-rotation-detail.html:193` + `project_updated:54-55, 175` — `farmer_action` & `evidence_coverage.before_changing`).
     - **Card 6: Why this result? (Accordion)** (`04-pal-rotation-detail.html:196` + `project_updated:167-176, 204-210, 265-269` — `Evidence coverage: High/Medium/Low`, `Known`, `Unknown`, `Answer basis`, and `FAMA AMI Market context` with non-promise disclaimer).
   - **Bottom Voice Hub (Screen 2 & 3):** `FAQ` circle button, Spinning 3D Earth (`"Hold to speak"` — pointer/keyboard hold records via `MediaRecorder` -> `/api/voice/turn`, plus live WS `msg.type === "pending_confirmation"` support), `EN`/`MS` pill toggle, and privacy helper text *"We do not keep your voice. We only save facts you confirm."* (with OpenAI transcription disclosure per `project_updated:405-412`).
   - **`Records` & `Settings` nav views:**
     - `Records`: Safe DOM rendering (`textContent`) of saved `FarmMemory` (`crop_history`, `soil`, `irrigation_availability`, confirmed `field_observations` with `zone`, `event_type`, `source`, `recorded_at`), **Export JSON** (`/export`), and **Delete Memory** (`DELETE /api/farms/{farm_id}`).
     - `Settings`: Only `locality`, `latitude`, `longitude`, `planting_month`, and historical `scenario` (`historical_average`, `dry_planting`, `heavy_rain_harvest`, `hot_season`) + Save (`POST /api/farms/{farm_id}/location`).

- [ ] **Step 1: Write the failing frontend wiring & Stitch parity test in `nasa/tests/test_app.py`**

Assert presence of all required backend endpoints, safety guards (`speechSynthesis`, `dialog.returnValue = ""`, `data.checkin`, `pending_confirmation`, `"Tell Farm Memory what happened"`), all 6 `Rotation detail` cards (`Climate and water fit`, `Soil and rotation benefit`, `Risks`, `Missing information`, `Before you decide`, `Why this result?`), Stitch labels (`Your Farms`, `YOU SAID`, `PAL SAYS`, `Hold to speak`, `"We do not keep your voice. We only save facts you confirm."`), and absence of unrequested widgets (no `leaflet`).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest nasa/tests/test_app.py::test_stitch_frontend_wiring_and_safety -v`
Expected: FAIL (`FileNotFoundError: ... nasa/static/index.html`).

- [ ] **Step 3: Implement `nasa/static/index.html` and verify safe DOM updates**

Build `nasa/static/index.html` strictly from the Stitch `PetaniPal` Claymorphism styles and components, keeping all dynamic values set via `textContent` / DOM nodes and calling `loadCheckIn()` on init, language toggle, and confirmation completion.

- [ ] **Step 4: Run full test suite to verify all tests pass**

Run: `uv run pytest nasa/tests/test_app.py -v`
Expected: All tests PASS with 0 failures.
