"""Deterministic Fuzzy-Threshold MCDA engine for 3-rotation crop comparison."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .context_data import load_geotanih_context, load_market_context
from .data_fetcher import DailyClimateSummary
from .farm_memory import FarmMemoryRecord

DEFAULT_CATALOG_PATH = Path("data/crops_catalog.json")


def load_crop_catalog(path: Path = DEFAULT_CATALOG_PATH) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["crops"]


def _trapezoid_score(val: float | None, opt_low: float, opt_high: float, margin: float) -> float:
    """Fuzzy trapezoidal membership in [0.0, 1.0]; returns 0.75 neutral if val is None."""
    if val is None:
        return 0.75
    if opt_low <= val <= opt_high:
        return 1.0
    if val < opt_low:
        return max(0.0, 1.0 - (opt_low - val) / max(1e-6, margin))
    return max(0.0, 1.0 - (val - opt_high) / max(1e-6, margin))


@dataclass
class RotationOption:
    crop_id: str
    crop_name_en: str
    crop_name_ms: str
    rotation_sequence_en: str
    rotation_sequence_ms: str
    is_existing: bool
    score: int
    resilience_band: str
    climate_water_fit_en: list[str]
    climate_water_fit_ms: list[str]
    soil_rotation_benefit_en: str
    soil_rotation_benefit_ms: str
    risks_en: list[str]
    risks_ms: list[str]
    farmer_action_en: str
    farmer_action_ms: str
    factor_scores: dict[str, int]
    market_context: dict[str, Any] = field(default_factory=dict)


@dataclass
class RotationComparison:
    locality: str
    scenario: str
    is_scenario_forecast: bool
    climate_summary: dict[str, Any]
    evidence_coverage: dict[str, Any]
    answer_basis: str
    rotations: list[dict[str, Any]]
    geotanih: dict[str, Any] = field(default_factory=dict)


def _score_single_crop(
    crop: dict[str, Any],
    climate: DailyClimateSummary,
    memory: FarmMemoryRecord,
    is_existing: bool,
    geotanih: dict[str, Any] | None = None,
    market_context: dict[str, Any] | None = None,
) -> RotationOption:
    opt = crop["optimal"]
    prev_crop_id = memory.last_crop if memory.last_crop != "unknown" else None

    # 1. Soil moisture & drainage fit (30%)
    wet_top = climate.recent_gwettop if climate.recent_gwettop is not None else climate.mean_gwettop
    wet_root = climate.recent_gwetroot if climate.recent_gwetroot is not None else climate.mean_gwetroot
    s_top = _trapezoid_score(wet_top, opt["gwettop"][0], opt["gwettop"][1], 0.25)
    s_root = _trapezoid_score(wet_root, opt["gwetroot"][0], opt["gwetroot"][1], 0.25)
    moisture_score = (s_top + s_root) / 2.0

    risks_en: list[str] = []
    risks_ms: list[str] = []
    fit_en: list[str] = []
    fit_ms: list[str] = []

    if memory.waterlogging_duration == "more_than_two_days" or memory.flooded_last_season == "yes":
        if crop["flood_tolerance"] == "low":
            moisture_score *= 0.65
            risks_en.append("High flood/waterlogging risk: farmer reported standing water >2 days or past flooding.")
            risks_ms.append("Risiko banjir/air bertakung tinggi: rekod ladang menunjukkan air bertakung >2 hari.")
        else:
            fit_en.append("Tolerates wet field conditions well based on your drainage history.")
            fit_ms.append("Tahan keadaan tanah lembap berdasarkan sejarah saliran ladang anda.")
    elif (geotanih or {}).get("drainage_class") in {"poor", "imperfect"} and crop["flood_tolerance"] == "low":
        moisture_score *= 0.85
        risks_en.append(
            f"GeoTanih district soil ({geotanih.get('soil_series', 'local clay')}) has {geotanih.get('drainage_class')} drainage (estimated from map)."
        )
        risks_ms.append(
            f"Tanah daerah GeoTanih ({geotanih.get('soil_series', 'tanah liat tempatan')}) mempunyai saliran {geotanih.get('drainage_class')} (anggaran peta)."
        )

    # 2. Water balance & rainfall (25%)
    rain_score = _trapezoid_score(
        climate.mean_monthly_rain_mm,
        opt["rain_monthly_mm"][0],
        opt["rain_monthly_mm"][1],
        120.0,
    )
    if memory.irrigation == "always" and climate.mean_monthly_rain_mm < opt["rain_monthly_mm"][0]:
        rain_score = min(1.0, rain_score + 0.25)
        fit_en.append("Farmer-confirmed irrigation offsets low historical rainfall.")
        fit_ms.append("Pengairan yang disahkan membantu menampung hujan yang rendah.")
    elif memory.irrigation == "no" and climate.longest_dry_spell_days >= 14 and crop["water_need"] == "high":
        rain_score *= 0.7
        risks_en.append(
            f"Dry-spell exposure ({climate.longest_dry_spell_days} days) with no irrigation for a high-water crop."
        )
        risks_ms.append(
            f"Risiko musim kering ({climate.longest_dry_spell_days} hari) tanpa pengairan untuk tanaman perlukan air tinggi."
        )

    if climate.heavy_rain_days_per_season >= 3.0 and crop["flood_tolerance"] == "low":
        risks_en.append(
            f"Heavy-rain storms ({climate.heavy_rain_days_per_season}/season >=30 mm) may damage roots or fruit."
        )
        risks_ms.append(
            f"Hujan lebat ({climate.heavy_rain_days_per_season} hari/musim >=30 mm) boleh menjejaskan akar atau buah."
        )

    # 3. Thermal suitability (20%)
    temp_score = _trapezoid_score(climate.mean_t2m, opt["t2m"][0], opt["t2m"][1], 5.0)
    if climate.mean_t2m_max > opt["t2m_max_limit"] or climate.hot_days_per_season >= 15:
        temp_score *= 0.8
        risks_en.append(f"Heat-stress days ({climate.hot_days_per_season}/season >34°C) may affect flowering.")
        risks_ms.append(f"Hari panas terik ({climate.hot_days_per_season} hari/musim >34°C) boleh menjejaskan pendebungaan.")
    else:
        fit_en.append(f"Temperature ({climate.mean_t2m}°C mean) fits the crop's thermal window.")
        fit_ms.append(f"Suhu purata ({climate.mean_t2m}°C) sesuai dengan julat tanaman.")

    # 4. Solar radiation (15%)
    solar_score = _trapezoid_score(climate.mean_solar_mj, opt["solar_mj"][0], opt["solar_mj"][1], 5.0)
    fit_en.append(f"Solar radiation averages {climate.mean_solar_mj} MJ/m²/day; water balance is {climate.water_balance_monthly_mm:+.1f} mm/mo.")
    fit_ms.append(f"Sinaran suria purata {climate.mean_solar_mj} MJ/m²/hari; imbangan air {climate.water_balance_monthly_mm:+.1f} mm/bulan.")

    # 5. Humidity / fungal disease pressure (10%)
    humid_score = 1.0 if climate.mean_rh2m <= opt["rh2m_max"] else max(0.3, 1.0 - (climate.mean_rh2m - opt["rh2m_max"]) / 15.0)
    if climate.high_humidity_days_per_season >= 20 and climate.mean_rh2m > opt["rh2m_max"]:
        risks_en.append(f"High humidity ({climate.mean_rh2m}% RH) raises fungal disease pressure.")
        risks_ms.append(f"Kelembapan tinggi ({climate.mean_rh2m}% RH) meningkatkan risiko penyakit kulat.")

    # Rotation & family benefit
    soil_benefit_en = f"Crop family: {crop['family']}; ground cover: {crop['ground_cover']}; nitrogen: {crop['nitrogen_effect']}."
    soil_benefit_ms = f"Keluarga tanaman: {crop['family']}; litupan tanah: {crop['ground_cover']}; keperluan nitrogen: {crop['nitrogen_effect']}."

    rotation_bonus = 0.0
    if prev_crop_id:
        if prev_crop_id == crop["crop_id"]:
            rotation_bonus = -0.06
            risks_en.append("Repeating the same crop continuously can build up host-specific pests and soil fatigue.")
            risks_ms.append("Menanam tanaman yang sama berterusan boleh mengumpul perosak dan meletihkan tanah.")
        else:
            rotation_bonus = 0.05
            soil_benefit_en = f"Breaks pest/disease cycle after {prev_crop_id.replace('_', ' ')}. " + soil_benefit_en
            soil_benefit_ms = f"Memutuskan kitaran perosak selepas {prev_crop_id.replace('_', ' ')}. " + soil_benefit_ms

    # Priority alignment nudge (subtle, never overrides climate safety)
    if memory.priority == "save_water" and crop["water_need"] in ("low-medium", "medium"):
        rotation_bonus += 0.03
    elif memory.priority == "lower_risk" and crop["flood_tolerance"] in ("medium", "high"):
        rotation_bonus += 0.02

    weighted = (
        0.30 * moisture_score
        + 0.25 * rain_score
        + 0.20 * temp_score
        + 0.15 * solar_score
        + 0.10 * humid_score
        + rotation_bonus
    )
    final_score = int(round(max(0.0, min(1.0, weighted)) * 100))
    band = "High" if final_score >= 78 else ("Moderate" if final_score >= 58 else "Low")

    prev_label_en = prev_crop_id.replace("_", " ").title() if prev_crop_id else "Current Field"
    prev_label_ms = prev_crop_id.replace("_", " ").title() if prev_crop_id else "Ladang Semasa"

    return RotationOption(
        crop_id=crop["crop_id"],
        crop_name_en=crop["name_en"],
        crop_name_ms=crop["name_ms"],
        rotation_sequence_en=f"{prev_label_en} -> {crop['name_en']}",
        rotation_sequence_ms=f"{prev_label_ms} -> {crop['name_ms']}",
        is_existing=is_existing,
        score=final_score,
        resilience_band=band,
        climate_water_fit_en=fit_en,
        climate_water_fit_ms=fit_ms,
        soil_rotation_benefit_en=soil_benefit_en,
        soil_rotation_benefit_ms=soil_benefit_ms,
        risks_en=risks_en or ["No major historical climate flags detected for this window."],
        risks_ms=risks_ms or ["Tiada risiko iklim sejarah utama dikesan untuk tempoh ini."],
        farmer_action_en=crop["management_tips_en"],
        farmer_action_ms=crop["management_tips_ms"],
        factor_scores={
            "moisture_drainage": round(moisture_score * 100),
            "water_balance": round(rain_score * 100),
            "thermal": round(temp_score * 100),
            "solar": round(solar_score * 100),
            "humidity_disease": round(humid_score * 100),
        },
        market_context=market_context or load_market_context(crop["crop_id"]),
    )


def compare_rotations(
    climate: DailyClimateSummary,
    memory: FarmMemoryRecord,
    catalog: list[dict[str, Any]] | None = None,
    geotanih: dict[str, Any] | None = None,
    market_lookup: dict[str, dict[str, Any]] | None = None,
) -> RotationComparison:
    """Compare existing rotation against the top two alternative rotations."""
    crops = catalog or load_crop_catalog()
    existing_id = memory.last_crop if memory.last_crop != "unknown" else "paddy_rice"
    district_key = memory.locality.split("(")[0].strip()
    geo = geotanih if geotanih is not None else load_geotanih_context(district_key)

    scored = [
        _score_single_crop(
            c,
            climate,
            memory,
            is_existing=(c["crop_id"] == existing_id),
            geotanih=geo,
            market_context=(market_lookup or {}).get(c["crop_id"]) or load_market_context(c["crop_id"]),
        )
        for c in crops
    ]

    existing_opts = [o for o in scored if o.is_existing]
    alt_opts = sorted([o for o in scored if not o.is_existing], key=lambda x: x.score, reverse=True)

    selected = (existing_opts[:1] + alt_opts[:2])[:3]
    known, unknown = memory.evidence_summary()
    if geo.get("evidence_label") == "estimated_from_climate_or_map":
        known.append(
            f"GeoTanih soil context ({geo.get('soil_series', 'unknown')}, drainage: {geo.get('drainage_class', 'unknown')}) — estimated from map"
        )
    coverage_level = "High" if len(unknown) <= 1 else ("Medium" if len(unknown) <= 3 else "Low")

    answer_basis = (
        f"NASA POWER daily AG history ({climate.history_years}, scenario={climate.scenario}), "
        f"reviewed Kedah crop library ({len(crops)} crops), "
        f"GeoTanih district soil context ({geo.get('soil_series', 'unknown')}), "
        f"FAMA AMI market context, "
        f"and farmer-confirmed Farm Memory ({memory.locality})."
    )
    if unknown:
        answer_basis += f" Unknown: {', '.join(unknown)}."

    return RotationComparison(
        locality=memory.locality,
        scenario=climate.scenario,
        is_scenario_forecast=False,
        climate_summary=asdict(climate),
        evidence_coverage={
            "level": coverage_level,
            "known": known,
            "unknown": unknown,
            "before_changing": (
                f"Verify {', '.join(unknown[:2])} and local buyer access before committing."
                if unknown
                else "Confirm local buyer access and seed availability before planting."
            ),
        },
        answer_basis=answer_basis,
        rotations=[asdict(o) for o in selected],
        geotanih=geo,
    )
