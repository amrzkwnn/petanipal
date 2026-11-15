from typing import Any, Dict, List, Optional

from schemas.crops import CropProfile, NitrogenEffect, ToleranceLevel, WaterNeed
from schemas.farm_memory import (
    EvidenceLabel,
    FarmMemory,
    IrrigationAvailability,
    SoilFeel,
    WaterloggingDuration,
)
from services.climate_service import DailyClimateSummary, NasaPowerClimateService
from services.geotanih_store import load_geotanih_context, load_market_context
from services.library_store import LibraryStore


def _resolve_evidence_coverage(memory: FarmMemory, geotanih: Dict[str, Any]) -> Dict[str, str]:
    coverage: Dict[str, str] = {}
    coverage["last_crop"] = (
        memory.crop_history[-1].evidence_label.value
        if memory.crop_history
        else EvidenceLabel.UNKNOWN.value
    )
    coverage["soil_texture"] = memory.soil.texture_feel.evidence_label.value
    coverage["drainage_tendency"] = memory.soil.waterlogging_duration.evidence_label.value
    coverage["water_source"] = memory.irrigation_availability.evidence_label.value
    coverage["flood_history"] = memory.soil.flooded_last_season.evidence_label.value
    coverage["soil_ph"] = memory.soil.ph.evidence_label.value
    coverage["climate"] = EvidenceLabel.ESTIMATED_FROM_CLIMATE.value
    ee = geotanih.get("evidence_label", EvidenceLabel.ESTIMATED_FROM_MAP)
    coverage["geotanih_soil_map"] = ee.value if isinstance(ee, EvidenceLabel) else str(ee)
    return coverage


def _score_crop(
    crop: CropProfile,
    last_crop_profile: Optional[CropProfile],
    memory: FarmMemory,
    climate: DailyClimateSummary,
    geotanih: Dict[str, Any],
) -> Dict[str, Any]:
    wl_val = memory.soil.waterlogging_duration.value
    wl_str = wl_val.value if isinstance(wl_val, WaterloggingDuration) else str(wl_val or "unknown")
    drainage_ev = memory.soil.waterlogging_duration.evidence_label
    if wl_str == "unknown":
        gt_drain = geotanih.get("drainage_tendency", "sometimes_stays_wet")
        wl_str = "over_2_days" if gt_drain == "often_waterlogged" else ("1_to_2_days" if gt_drain == "sometimes_stays_wet" else "same_day")
        drainage_ev = geotanih.get("evidence_label", EvidenceLabel.ESTIMATED_FROM_MAP)

    tex_val = memory.soil.texture_feel.value
    tex_str = tex_val.value if isinstance(tex_val, SoilFeel) else str(tex_val or "unknown")
    texture_ev = memory.soil.texture_feel.evidence_label
    if tex_str == "unknown":
        gt_tex = geotanih.get("dominant_texture", "loam")
        tex_str = "sticky" if gt_tex == "clay" else ("sandy" if gt_tex == "sandy" else "in_between")
        texture_ev = geotanih.get("evidence_label", EvidenceLabel.ESTIMATED_FROM_MAP)

    irr_val = memory.irrigation_availability.value
    water_src = irr_val.value if isinstance(irr_val, IrrigationAvailability) else str(irr_val or "unknown")
    flood_hist = str(memory.soil.flooded_last_season.value or "unknown")

    water_fit_en: List[str] = []
    water_fit_ms: List[str] = []
    soil_benefit_en: List[str] = []
    soil_benefit_ms: List[str] = []
    risks_en: List[str] = []
    risks_ms: List[str] = []
    missing_en: List[str] = []
    missing_ms: List[str] = []
    actions_en: List[str] = []
    actions_ms: List[str] = []

    water_fit_level = "Good"
    soil_benefit_level = "Medium"
    risk_level = "Low"

    is_dry_spell = (
        climate.longest_dry_spell_days >= 6 or climate.planting_window_rain_low
    ) and water_src in ("no", "unknown")

    flood_tol = (
        crop.flood_tolerance.value
        if isinstance(crop.flood_tolerance, ToleranceLevel)
        else str(crop.flood_tolerance)
    )
    water_need = (
        crop.water_need.value
        if isinstance(crop.water_need, WaterNeed)
        else str(crop.water_need)
    )
    n_effect = (
        crop.nitrogen_effect.value
        if isinstance(crop.nitrogen_effect, NitrogenEffect)
        else str(crop.nitrogen_effect)
    )
    ev_str = drainage_ev.value if isinstance(drainage_ev, EvidenceLabel) else str(drainage_ev)
    tex_ev_str = texture_ev.value if isinstance(texture_ev, EvidenceLabel) else str(texture_ev)

    if flood_tol == "low" and (
        wl_str in ("over_2_days", "1_to_2_days")
        or flood_hist == "yes"
        or climate.heavy_rain_days_30d >= 3
    ):
        water_fit_level = "Poor" if wl_str == "over_2_days" else "Watch"
        risk_level = "High"
        water_fit_en.append(
            "Doesn't handle standing water well, and recent weather has been quite rainy for this plot."
        )
        water_fit_ms.append(
            "Kurang tahan air bertakung, dan cuaca kebelakangan ini agak kerap hujan untuk petak ini."
        )
        risks_en.append(
            "Roots can rot if heavy rain leaves water standing; raised beds with clear drains help."
        )
        risks_ms.append(
            "Akar mudah reput jika air bertakung semasa hujan lebat; batas tinggi dan parit yang lancar membantu."
        )
        actions_en.append(
            "Build raised beds and clear side drains before planting."
        )
        actions_ms.append(
            "Buat batas tinggi dan bersihkan parit tepi sebelum menanam."
        )
    elif is_dry_spell and water_need in ("high", "medium_high"):
        water_fit_level = "Watch"
        if risk_level == "Low":
            risk_level = "Medium"
        water_fit_en.append(
            "Needs steady watering, while recent weather has had dry spells."
        )
        water_fit_ms.append(
            "Perlukan air yang sekata, sedangkan cuaca kebelakangan ini ada tempoh kering."
        )
        risks_en.append(
            "Young plants or flowers may dry out if they rely only on rain."
        )
        risks_ms.append(
            "Pokok muda atau bunga mudah layu jika bergantung kepada hujan sahaja."
        )
        actions_en.append(
            "Use mulch around the plants and keep backup water ready for dry days."
        )
        actions_ms.append(
            "Gunakan sungkupan dan sediakan air siraman tambahan semasa hari kering."
        )
    else:
        water_fit_en.append(
            "Matches recent rainfall and how well this plot drains."
        )
        water_fit_ms.append(
            "Sesuai dengan keadaan hujan kebelakangan ini dan saliran petak ini."
        )

    if last_crop_profile:
        if last_crop_profile.family.lower() == crop.family.lower():
            soil_benefit_level = "Low"
            risk_level = "High"
            soil_benefit_en.append(
                f"Too similar to your last crop ({last_crop_profile.names['en'][0]}): won't break pest and disease buildup."
            )
            soil_benefit_ms.append(
                f"Terlalu serupa dengan tanaman lepas ({last_crop_profile.names['ms'][0]}): tidak memutuskan kitaran perosak dan penyakit."
            )
            risks_en.append(
                "Planting the same crop family back-to-back increases pest and soil disease risk."
            )
            risks_ms.append(
                "Menanam kumpulan tanaman yang sama berturut-turut meningkatkan risiko perosak dan penyakit tanah."
            )
        elif n_effect == "nitrogen_fixing":
            soil_benefit_level = "High"
            soil_benefit_en.append(
                f"Legume crop naturally feeds soil nitrogen and helps break pests after {last_crop_profile.names['en'][0]}."
            )
            soil_benefit_ms.append(
                f"Tanaman kekacang membantu menyuburkan tanah dan memutuskan perosak selepas {last_crop_profile.names['ms'][0]}."
            )
        else:
            soil_benefit_level = "High"
            soil_benefit_en.append(
                f"Good change from {last_crop_profile.names['en'][0]} to help break pest and disease cycles."
            )
            soil_benefit_ms.append(
                f"Pertukaran baik daripada {last_crop_profile.names['ms'][0]} untuk membantu memutuskan kitaran perosak dan penyakit."
            )
    else:
        if n_effect == "nitrogen_fixing":
            soil_benefit_level = "High"
            soil_benefit_en.append(
                "Legume crop naturally feeds soil nitrogen for your next harvest."
            )
            soil_benefit_ms.append(
                "Tanaman kekacang membantu menambah kesuburan tanah secara semula jadi."
            )
        else:
            soil_benefit_en.append(
                "Good rotation option to keep the plot productive."
            )
            soil_benefit_ms.append(
                "Pilihan giliran yang baik untuk mengekalkan kesuburan petak."
            )

    crop_terms = [
        n.lower() for n in (crop.names.get("en", []) + crop.names.get("ms", []))
    ] + [crop.crop_id.lower(), crop.family.lower()]
    for obs in memory.field_observations:
        obs_text = (obs.observation or "").lower()
        aff_crop = (obs.affected_crop or "").lower()
        cat_lower = (obs.event_type or "general").lower()
        zone_txt = f" in {obs.zone}" if obs.zone and obs.zone != "general" else ""
        if (
            any(term in obs_text or term in aff_crop for term in crop_terms)
            or (
                cat_lower in ("pest", "disease")
                and last_crop_profile
                and last_crop_profile.family.lower() == crop.family.lower()
            )
        ):
            risk_level = "High"
            risks_en.append(
                f"Recorded field observation ({obs.event_type}{zone_txt}): '{obs.observation}' increases carryover risk for {crop.names['en'][0]}."
            )
            risks_ms.append(
                f"Pemerhatian ladang direkodkan ({obs.event_type}{zone_txt}): '{obs.observation}' meningkatkan risiko berulang bagi {crop.names['ms'][0]}."
            )
            actions_en.append(
                f"Inspect {obs.zone or 'affected beds'} and remove infected crop residue before planting."
            )
            actions_ms.append(
                f"Periksa {obs.zone or 'batas terlibat'} dan buang sisa tanaman berjangkit sebelum menanam."
            )
        elif cat_lower in ("flooding", "waterlogging", "drainage") and flood_tol == "low":
            if risk_level == "Low":
                risk_level = "Medium"
            risks_en.append(
                f"Logged waterlogging observation{zone_txt} ('{obs.observation}') conflicts with low flood tolerance."
            )
            risks_ms.append(
                f"Pemerhatian air bertakung{zone_txt} ('{obs.observation}') bercanggah dengan toleransi banjir rendah."
            )

    if not memory.crop_history:
        missing_en.append("Last crop planted on this plot is not yet confirmed by farmer.")
        missing_ms.append("Tanaman terakhir di petak ini belum disahkan oleh petani.")
    if memory.soil.texture_feel.evidence_label != EvidenceLabel.VERIFIED_BY_FARMER:
        missing_en.append(
            "Soil feel by hand is not confirmed by you yet."
        )
        missing_ms.append(
            "Tekstur tanah belum disahkan oleh anda lagi."
        )
    if memory.soil.waterlogging_duration.evidence_label != EvidenceLabel.VERIFIED_BY_FARMER:
        missing_en.append(
            "Confirm how long rainwater stands in this plot after heavy rain."
        )
        missing_ms.append(
            "Sahkan berapa lama air bertakung di petak ini selepas hujan lebat."
        )
    if memory.irrigation_availability.evidence_label != EvidenceLabel.VERIFIED_BY_FARMER:
        missing_en.append("Backup watering source during dry days is not confirmed yet.")
        missing_ms.append("Sumber air siraman tambahan semasa hari kering belum disahkan.")

    if not risks_en:
        risks_en.append(
            crop.rotation_warnings[0]
            if crop.rotation_warnings
            else "Watch plot drainage after heavy downpours."
        )
        risks_ms.append(
            "Pantau saliran petak selepas hujan lebat dan elakkan ulang jenis tanaman yang sama."
        )

    if not actions_en:
        actions_en.append(
            "Check top soil moisture and make sure drains are clear before planting."
        )
        actions_ms.append(
            "Periksa kelembapan tanah atas dan pastikan parit saliran bersih sebelum menanam."
        )

    mkt = load_market_context(crop.crop_id)
    summary_en = (
        f"{crop.names['en'][0].title()}: "
        f"Water fit {water_fit_level}, Soil benefit {soil_benefit_level}, Risk {risk_level}."
    )
    summary_ms = (
        f"{crop.names['ms'][0].title()}: "
        f"Kesesuaian air {water_fit_level}, Manfaat tanah {soil_benefit_level}, Risiko {risk_level}."
    )

    return {
        "crop_id": crop.crop_id,
        "name_en": crop.names["en"][0].title(),
        "name_ms": crop.names["ms"][0].title(),
        "family": crop.family,
        "duration_days": {"min": crop.duration_days.min, "max": crop.duration_days.max},
        "unlisted": False,
        "water_fit_level": water_fit_level,
        "soil_benefit_level": soil_benefit_level,
        "risk_level": risk_level,
        "climate_water_fit_en": water_fit_en,
        "climate_water_fit_ms": water_fit_ms,
        "soil_rotation_benefit_en": soil_benefit_en,
        "soil_rotation_benefit_ms": soil_benefit_ms,
        "risks_en": risks_en,
        "risks_ms": risks_ms,
        "missing_info_en": missing_en,
        "missing_info_ms": missing_ms,
        "farmer_action_en": actions_en[0],
        "farmer_action_ms": actions_ms[0],
        "summary_sentence_en": summary_en,
        "summary_sentence_ms": summary_ms,
        "market_context": mkt,
    }


def _build_unlisted_option(raw_name: str, climate: DailyClimateSummary) -> Dict[str, Any]:
    slug = "".join(ch if ch.isalnum() else "_" for ch in raw_name.strip().lower()).strip("_") or "crop"
    title = raw_name.strip().title()
    return {
        "crop_id": f"unlisted_{slug}",
        "name_en": title,
        "name_ms": title,
        "family": "Unlisted / Local Variety",
        "duration_days": {"min": 60, "max": 120},
        "unlisted": True,
        "water_fit_level": "Unknown",
        "soil_benefit_level": "Unknown",
        "risk_level": "Medium",
        "climate_water_fit_en": [
            f"{title} is not yet in our local crop guide; recent weather and plot drainage still matter before planting."
        ],
        "climate_water_fit_ms": [
            f"{title} belum ada dalam panduan tanaman tempatan; cuaca kebelakangan ini dan saliran petak tetap penting sebelum menanam."
        ],
        "soil_rotation_benefit_en": [
            "Check that it is a different crop group from what you planted last."
        ],
        "soil_rotation_benefit_ms": [
            "Pastikan ia daripada kumpulan tanaman berbeza daripada tanaman lepas."
        ],
        "risks_en": [
            f"Local growing notes for {title} are not verified yet; double-check drainage and pest risks locally."
        ],
        "risks_ms": [
            f"Nota tanaman tempatan bagi {title} belum disahkan; semak kesesuaian saliran dan risiko perosak dahulu."
        ],
        "missing_info_en": [
            f"Local water and flood-tolerance details for {title} are not in our guide yet."
        ],
        "missing_info_ms": [
            f"Maklumat keperluan air dan toleransi banjir tempatan bagi {title} belum lengkap."
        ],
        "farmer_action_en": f"Ask a local agriculture officer whether {title} handles heavy rain or dry days well on your soil.",
        "farmer_action_ms": f"Tanya pegawai pertanian tempatan sama ada {title} sesuai dengan hujan lebat atau hari kering di tanah anda.",
        "summary_sentence_en": f"{title}: Not in our local guide yet — check drainage fit and crop group before planting.",
        "summary_sentence_ms": f"{title}: Belum ada dalam panduan — semak kesesuaian saliran dan jenis tanaman sebelum menanam.",
        "market_context": load_market_context(slug),
    }


def compare_rotations(
    memory: FarmMemory,
    libraries: LibraryStore,
    climate: Optional[DailyClimateSummary] = None,
    candidate_crop_names: Optional[List[str]] = None,
    candidate_crop_ids: Optional[List[str]] = None,
    scenario: str = "normal",
) -> Dict[str, Any]:
    lat = memory.location.latitude or 5.647
    lon = memory.location.longitude or 100.487
    if climate is None:
        climate = NasaPowerClimateService().get_summary(
            lat, lon, scenario=scenario, allow_network=False
        )

    geotanih = load_geotanih_context(memory.location.locality or "Sungai Petani, Kedah")
    last_crop_name = memory.crop_history[-1].raw_crop_name if memory.crop_history else None
    last_crop_id = memory.crop_history[-1].crop_id if memory.crop_history else None
    last_crop_profile = (
        libraries.get_crop(last_crop_id)
        if last_crop_id
        else (libraries.match_crop_name(last_crop_name) if last_crop_name else None)
    )

    options: List[Dict[str, Any]] = []
    seen_ids = set()

    requested_names = candidate_crop_names or candidate_crop_ids or []
    for raw_name in requested_names:
        matched = libraries.match_crop_name(raw_name) or libraries.get_crop(raw_name)
        if matched is not None:
            if matched.crop_id not in seen_ids:
                seen_ids.add(matched.crop_id)
                options.append(
                    _score_crop(matched, last_crop_profile, memory, climate, geotanih)
                )
        else:
            unlisted_opt = _build_unlisted_option(raw_name, climate)
            if unlisted_opt["crop_id"] not in seen_ids:
                seen_ids.add(unlisted_opt["crop_id"])
                options.append(unlisted_opt)

    rank_order = {"Low": 0, "Lower": 0, "Medium": 1, "High": 2}
    water_order = {"Good": 0, "High": 0, "Medium": 1, "Poor": 2, "Low": 2, "Unknown": 3}
    soil_order = {"High": 0, "Medium": 1, "Low": 2, "Unknown": 3}

    fallback_candidates: List[Dict[str, Any]] = []
    for crop in libraries.crop_library.crops:
        if crop.crop_id in seen_ids:
            continue
        fallback_candidates.append(
            _score_crop(crop, last_crop_profile, memory, climate, geotanih)
        )
    fallback_candidates.sort(
        key=lambda o: (
            rank_order.get(o["risk_level"], 2),
            water_order.get(o["water_fit_level"], 3),
            soil_order.get(o["soil_benefit_level"], 2),
        )
    )

    for cand in fallback_candidates:
        if len(options) >= 3:
            break
        seen_ids.add(cand["crop_id"])
        options.append(cand)

    if not requested_names:
        options.sort(
            key=lambda o: (
                1 if o.get("unlisted") else 0,
                rank_order.get(o["risk_level"], 2),
                water_order.get(o["water_fit_level"], 3),
                soil_order.get(o["soil_benefit_level"], 2),
            )
        )

    evidence_coverage = _resolve_evidence_coverage(memory, geotanih)
    verified_count = sum(
        1 for v in evidence_coverage.values() if v == EvidenceLabel.VERIFIED_BY_FARMER.value
    )
    answer_basis = {
        "verified_by_farmer": [
            k for k, v in evidence_coverage.items() if v == EvidenceLabel.VERIFIED_BY_FARMER.value
        ],
        "estimated_from_map": [
            k for k, v in evidence_coverage.items() if v == EvidenceLabel.ESTIMATED_FROM_MAP.value
        ],
        "estimated_from_climate": [
            k for k, v in evidence_coverage.items() if v == EvidenceLabel.ESTIMATED_FROM_CLIMATE.value
        ],
        "unknown": [
            k for k, v in evidence_coverage.items() if v == EvidenceLabel.UNKNOWN.value
        ],
        "verified_count": verified_count,
    }

    recorded_observations = [
        {
            "category": obs.event_type,
            "summary": obs.observation,
            "zone": obs.zone,
            "affected_crop": obs.affected_crop,
            "evidence_label": obs.evidence_label.value,
            "observed_at": obs.recorded_at.isoformat(),
        }
        for obs in memory.field_observations
    ]

    return {
        "farm_id": memory.farm_id,
        "scenario": scenario,
        "last_crop": last_crop_name or "unknown",
        "options": options[:3],
        "climate_summary": climate.model_dump(mode="json"),
        "geotanih_context": geotanih,
        "evidence_coverage": evidence_coverage,
        "answer_basis": answer_basis,
        "missing_info": options[0].get("missing_info_en", []) if options else [],
        "recorded_observations": recorded_observations,
        "advisory_disclaimer_en": "Options compare agronomic trade-offs for your plot; final crop selection remains the farmer's decision.",
        "advisory_disclaimer_ms": "Pilihan membandingkan kesesuaian agronomi bagi petak anda; keputusan akhir tanaman kekal di tangan petani.",
    }
