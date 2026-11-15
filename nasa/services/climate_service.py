import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import httpx
from pydantic import BaseModel, Field

from schemas.farm_memory import EvidenceLabel


class DailyClimateSummary(BaseModel):
    lat: float
    lon: float
    rain_7d_mm: float
    rain_30d_mm: float
    heavy_rain_days_30d: int
    longest_dry_spell_days: int
    dry_spell_count: int = 0
    avg_max_temp_c: float
    hot_days_30d: int
    planting_window_rain_low: bool = False
    heavy_rain_near_harvest: bool = False
    hot_days_during_flowering: int = 0
    plain_insights_en: List[str] = Field(default_factory=list)
    plain_insights_ms: List[str] = Field(default_factory=list)
    scenario: str = "normal"
    evidence_label: EvidenceLabel = EvidenceLabel.ESTIMATED_FROM_CLIMATE
    source_note: str = "NASA POWER Agroclimatology Daily (PRECTOTCORR, T2M_MAX, T2M_MIN)"


def compute_climate_summary(
    lat: float,
    lon: float,
    precip: Dict[str, float],
    tmax: Dict[str, float],
    tmin: Optional[Dict[str, float]] = None,
    scenario: str = "normal",
    duration_days: int = 75,
    source_note: str = "NASA POWER Agroclimatology Daily (PRECTOTCORR, T2M_MAX, T2M_MIN)",
) -> DailyClimateSummary:
    valid_days = sorted(k for k, v in precip.items() if v is not None and v >= 0)
    last_30 = valid_days[-30:] if len(valid_days) >= 30 else valid_days
    last_7 = last_30[-7:] if len(last_30) >= 7 else last_30

    rain_factor = 1.0
    temp_offset = 0.0
    if scenario == "drier":
        rain_factor = 0.65
        temp_offset = 0.8
    elif scenario == "wetter":
        rain_factor = 1.35
        temp_offset = -0.3

    r30_vals = [max(0.0, float(precip[d]) * rain_factor) for d in last_30]
    r7_vals = [max(0.0, float(precip[d]) * rain_factor) for d in last_7]
    t30_vals = [
        float(tmax.get(d, 32.0)) + temp_offset
        for d in last_30
        if tmax.get(d, -999) > -90
    ]

    rain_30d = round(sum(r30_vals), 1)
    rain_7d = round(sum(r7_vals), 1)
    heavy_days = sum(1 for v in r30_vals if v >= 20.0)

    longest_dry = 0
    cur_dry = 0
    dry_spell_count = 0
    for v in r30_vals:
        if v < 1.0:
            cur_dry += 1
            if cur_dry > longest_dry:
                longest_dry = cur_dry
        else:
            if cur_dry >= 5:
                dry_spell_count += 1
            cur_dry = 0
    if cur_dry >= 5:
        dry_spell_count += 1

    avg_tmax = round(sum(t30_vals) / len(t30_vals), 1) if t30_vals else 32.0
    hot_days = sum(1 for t in t30_vals if t >= 34.0)

    n = len(r30_vals)
    third = max(1, n // 3)
    planting_vals = r30_vals[:third]
    flowering_t_vals = t30_vals[third : 2 * third] if len(t30_vals) >= 2 * third else t30_vals
    harvest_vals = r30_vals[2 * third :]

    planting_window_rain_low = sum(planting_vals) < 15.0
    heavy_rain_near_harvest = any(v >= 20.0 for v in harvest_vals) or sum(harvest_vals) >= 95.0
    hot_days_during_flowering = sum(1 for t in flowering_t_vals if t >= 34.0)

    insights_en: List[str] = []
    insights_ms: List[str] = []

    if planting_window_rain_low or longest_dry >= 5:
        insights_en.append(
            "Recent dry spell means new seedlings may need extra watering at the start."
        )
        insights_ms.append(
            "Cuaca agak kering kebelakangan ini, jadi anak benih mungkin perlukan siraman tambahan pada awalnya."
        )
    else:
        insights_en.append(
            "Recent rain has left enough soil moisture for young plants to get started."
        )
        insights_ms.append(
            "Hujan kebelakangan ini memberi kelembapan tanah yang cukup untuk permulaan tanaman."
        )

    if heavy_rain_near_harvest or heavy_days >= 3:
        insights_en.append(
            "Heavy downpours were common recently; plots that drain slowly may pool water, so clear drains or plant on raised beds."
        )
        insights_ms.append(
            "Hujan lebat agak kerap kebelakangan ini; petak yang lambat mengalirkan air berisiko bertakung, jadi pastikan parit bersih atau guna batas tinggi."
        )

    if hot_days_during_flowering >= 3 or avg_tmax >= 33.5:
        insights_en.append(
            "Hot afternoons can stress flowers; mulching and morning watering can help."
        )
        insights_ms.append(
            "Cuaca tengah hari yang panas boleh meletihkan bunga; sungkupan dan siraman pagi boleh membantu."
        )

    if len(insights_en) < 2:
        insights_en.append(
            "Overall recent rainfall looks steady enough for normal planting and care."
        )
        insights_ms.append(
            "Secara keseluruhan, hujan kebelakangan ini agak stabil untuk penanaman dan penjagaan biasa."
        )

    return DailyClimateSummary(
        lat=lat,
        lon=lon,
        rain_7d_mm=rain_7d,
        rain_30d_mm=rain_30d,
        heavy_rain_days_30d=heavy_days,
        longest_dry_spell_days=longest_dry,
        dry_spell_count=dry_spell_count,
        avg_max_temp_c=avg_tmax,
        hot_days_30d=hot_days,
        planting_window_rain_low=planting_window_rain_low,
        heavy_rain_near_harvest=heavy_rain_near_harvest,
        hot_days_during_flowering=hot_days_during_flowering,
        plain_insights_en=insights_en[:3],
        plain_insights_ms=insights_ms[:3],
        scenario=scenario,
        evidence_label=EvidenceLabel.ESTIMATED_FROM_CLIMATE,
        source_note=source_note,
    )


class NasaPowerClimateService:
    BASE_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"

    def __init__(self, cache_dir: Optional[Path] = None) -> None:
        self.cache_dir = cache_dir or (Path(__file__).resolve().parents[1] / "storage" / "climate_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_file(self, lat: float, lon: float) -> Path:
        return self.cache_dir / f"power_{round(lat, 2)}_{round(lon, 2)}.json"

    def get_summary(
        self,
        lat: float,
        lon: float,
        scenario: str = "normal",
        duration_days: int = 75,
        allow_network: bool = True,
    ) -> DailyClimateSummary:
        cache_path = self._cache_file(lat, lon)
        payload = None
        if cache_path.exists():
            try:
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
            except Exception:
                payload = None

        if payload is None and allow_network:
            end_dt = datetime.now(timezone.utc) - timedelta(days=2)
            start_dt = end_dt - timedelta(days=35)
            params = {
                "parameters": "PRECTOTCORR,T2M_MAX,T2M_MIN",
                "community": "AG",
                "longitude": round(lon, 4),
                "latitude": round(lat, 4),
                "start": start_dt.strftime("%Y%m%d"),
                "end": end_dt.strftime("%Y%m%d"),
                "format": "JSON",
            }
            try:
                with httpx.Client(timeout=8.0) as client:
                    resp = client.get(self.BASE_URL, params=params)
                    resp.raise_for_status()
                    payload = resp.json()
                    cache_path.write_text(json.dumps(payload), encoding="utf-8")
            except Exception:
                payload = None

        if payload and "properties" in payload and "parameter" in payload["properties"]:
            param = payload["properties"]["parameter"]
            precip = param.get("PRECTOTCORR", {})
            tmax = param.get("T2M_MAX", {})
            tmin = param.get("T2M_MIN", {})
            return compute_climate_summary(
                lat=lat,
                lon=lon,
                precip=precip,
                tmax=tmax,
                tmin=tmin,
                scenario=scenario,
                duration_days=duration_days,
                source_note="NASA POWER Agroclimatology Daily (live/cached)",
            )

        fallback_precip = {
            f"202603{i:02d}": (24.0 if i in (4, 12, 21) else (0.0 if 14 <= i <= 19 else 4.2))
            for i in range(1, 31)
        }
        fallback_tmax = {
            f"202603{i:02d}": (34.4 if i in (15, 16, 17, 18) else 32.4)
            for i in range(1, 31)
        }
        fallback_tmin = {f"202603{i:02d}": 24.2 for i in range(1, 31)}
        return compute_climate_summary(
            lat=lat,
            lon=lon,
            precip=fallback_precip,
            tmax=fallback_tmax,
            tmin=fallback_tmin,
            scenario=scenario,
            duration_days=duration_days,
            source_note="NASA POWER Kedah agroclimatology baseline (offline fallback)",
        )
