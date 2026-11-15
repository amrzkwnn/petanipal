"""Fetch and compute daily NASA POWER agroclimatology features."""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import requests

POINT_DAILY_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
DAILY_PARAMS = "PRECTOTCORR,T2M,T2M_MAX,T2M_MIN,RH2M,ALLSKY_SFC_SW_DWN,GWETTOP,GWETROOT"
FILL_VALUE = -999.0


@dataclass(frozen=True)
class DailyClimateSummary:
    """Computed daily climate features for a locality and 3-month planting window."""

    latitude: float
    longitude: float
    planting_month: int
    scenario: str
    history_years: str
    recent_rain_7d_mm: float
    recent_rain_30d_mm: float
    recent_gwettop: float | None
    recent_gwetroot: float | None
    mean_monthly_rain_mm: float
    mean_et0_monthly_mm: float
    water_balance_monthly_mm: float
    longest_dry_spell_days: int
    heavy_rain_days_per_season: float
    hot_days_per_season: float
    high_humidity_days_per_season: float
    mean_t2m: float
    mean_t2m_max: float
    mean_solar_mj: float
    mean_rh2m: float
    mean_gwettop: float | None
    mean_gwetroot: float | None

    @property
    def recent_7d_rain_mm(self) -> float:
        return self.recent_rain_7d_mm

    @property
    def recent_30d_rain_mm(self) -> float:
        return self.recent_rain_30d_mm


def _clean(val: Any) -> float | None:
    if val is None:
        return None
    f = float(val)
    if math.isclose(f, FILL_VALUE, abs_tol=1e-4):
        return None
    return f


def _hargreaves_et0_mm_day(t_mean: float, t_max: float, t_min: float, solar_mj: float) -> float:
    """Estimate daily reference ET0 (mm/day) from temperature and solar radiation."""
    td = max(0.0, t_max - t_min)
    # Using Makkink/Hargreaves hybrid with observed Rs (MJ/m2/day)
    return max(0.5, 0.0135 * (t_mean + 17.78) * (solar_mj / 2.45) * (1.0 + 0.015 * td))


def _longest_dry_spell(precip_series: list[float]) -> int:
    best = 0
    curr = 0
    for p in precip_series:
        if p < 1.0:
            curr += 1
            best = max(best, curr)
        else:
            curr = 0
    return best


def _normalize_daily_params(daily_params: dict[str, dict[str, float]] | pd.DataFrame) -> dict[str, dict[str, float]]:
    if not isinstance(daily_params, pd.DataFrame):
        return daily_params
    df = daily_params.copy()
    date_keys = [pd.Timestamp(d).strftime("%Y%m%d") for d in df["date"]]
    out: dict[str, dict[str, float]] = {}
    for col in df.columns:
        if col == "date":
            continue
        out[str(col)] = {k: float(v) for k, v in zip(date_keys, df[col], strict=False) if pd.notna(v)}
    return out


def compute_climate_summary(
    daily_params: dict[str, dict[str, float]] | pd.DataFrame,
    latitude: float = 6.0704075,
    longitude: float = 100.3557400,
    planting_month: int = 1,
    scenario: str = "historical_average",
) -> DailyClimateSummary:
    """Compute seasonal & recent daily climate features from NASA POWER daily JSON."""
    daily_params = _normalize_daily_params(daily_params)
    dates = sorted(daily_params.get("PRECTOTCORR", {}).keys())
    if not dates:
        raise RuntimeError("No daily precipitation records returned from NASA POWER.")

    # Recent 30-day & 7-day baseline from latest available valid dates
    recent_dates = dates[-30:]
    recent_7 = dates[-7:]

    def _valid_vals(param: str, keys: list[str]) -> list[float]:
        out: list[float] = []
        pmap = daily_params.get(param, {})
        for k in keys:
            v = _clean(pmap.get(k))
            if v is not None:
                out.append(v)
        return out

    recent_rain_30 = sum(_valid_vals("PRECTOTCORR", recent_dates))
    recent_rain_7 = sum(_valid_vals("PRECTOTCORR", recent_7))
    r_top = _valid_vals("GWETTOP", recent_dates)
    r_root = _valid_vals("GWETROOT", recent_dates)

    # Group historical records into 3-month planting windows starting at planting_month
    target_months = {((planting_month - 1 + offset) % 12) + 1 for offset in range(3)}
    seasons: dict[int, list[str]] = {}
    for d_str in dates:
        yr = int(d_str[:4])
        mo = int(d_str[4:6])
        if mo in target_months:
            season_yr = yr - 1 if (planting_month > 10 and mo < planting_month) else yr
            seasons.setdefault(season_yr, []).append(d_str)

    # Keep complete or substantial seasons (>= 60 days)
    valid_seasons = {yr: keys for yr, keys in seasons.items() if len(keys) >= 60}
    if not valid_seasons:
        valid_seasons = {int(dates[0][:4]): dates}

    # Pick all seasons for historical_average, or the extreme historical year for what-if
    if scenario == "dry_planting":
        chosen_yr = min(valid_seasons, key=lambda y: sum(_valid_vals("PRECTOTCORR", valid_seasons[y])))
        selected_seasons = {chosen_yr: valid_seasons[chosen_yr]}
    elif scenario == "heavy_rain_harvest":
        chosen_yr = max(valid_seasons, key=lambda y: sum(_valid_vals("PRECTOTCORR", valid_seasons[y])))
        selected_seasons = {chosen_yr: valid_seasons[chosen_yr]}
    elif scenario == "hot_season":
        chosen_yr = max(
            valid_seasons,
            key=lambda y: (
                sum(_valid_vals("T2M_MAX", valid_seasons[y]))
                / max(1, len(_valid_vals("T2M_MAX", valid_seasons[y])))
            ),
        )
        selected_seasons = {chosen_yr: valid_seasons[chosen_yr]}
    else:
        selected_seasons = valid_seasons

    season_rain_totals: list[float] = []
    dry_spells: list[int] = []
    heavy_days: list[int] = []
    hot_days: list[int] = []
    humid_days: list[int] = []
    all_keys: list[str] = []

    for keys in selected_seasons.values():
        all_keys.extend(keys)
        p_vals = _valid_vals("PRECTOTCORR", keys)
        tmax_vals = _valid_vals("T2M_MAX", keys)
        rh_vals = _valid_vals("RH2M", keys)

        season_rain_totals.append(sum(p_vals))
        dry_spells.append(_longest_dry_spell(p_vals))
        heavy_days.append(sum(1 for p in p_vals if p >= 30.0))
        hot_days.append(sum(1 for t in tmax_vals if t > 34.0))
        humid_days.append(sum(1 for h in rh_vals if h > 85.0))

    n_seasons = len(selected_seasons)
    t2m_vals = _valid_vals("T2M", all_keys)
    tmax_all = _valid_vals("T2M_MAX", all_keys)
    tmin_all = _valid_vals("T2M_MIN", all_keys)
    solar_vals = _valid_vals("ALLSKY_SFC_SW_DWN", all_keys)
    rh_all = _valid_vals("RH2M", all_keys)
    top_all = _valid_vals("GWETTOP", all_keys)
    root_all = _valid_vals("GWETROOT", all_keys)

    mean_t2m = sum(t2m_vals) / max(1, len(t2m_vals))
    mean_tmax = sum(tmax_all) / max(1, len(tmax_all))
    mean_tmin = sum(tmin_all) / max(1, len(tmin_all))
    mean_solar = sum(solar_vals) / max(1, len(solar_vals))
    mean_rh = sum(rh_all) / max(1, len(rh_all))

    mean_monthly_rain = (sum(season_rain_totals) / n_seasons) / 3.0
    et0_monthly = _hargreaves_et0_mm_day(mean_t2m, mean_tmax, mean_tmin, mean_solar) * 30.0
    years_sorted = sorted(selected_seasons.keys())
    hist_label = f"{years_sorted[0]}" if len(years_sorted) == 1 else f"{years_sorted[0]}-{years_sorted[-1]}"

    return DailyClimateSummary(
        latitude=latitude,
        longitude=longitude,
        planting_month=planting_month,
        scenario=scenario,
        history_years=hist_label,
        recent_rain_7d_mm=round(recent_rain_7, 1),
        recent_rain_30d_mm=round(recent_rain_30, 1),
        recent_gwettop=round(sum(r_top) / len(r_top), 3) if r_top else None,
        recent_gwetroot=round(sum(r_root) / len(r_root), 3) if r_root else None,
        mean_monthly_rain_mm=round(mean_monthly_rain, 1),
        mean_et0_monthly_mm=round(et0_monthly, 1),
        water_balance_monthly_mm=round(mean_monthly_rain - et0_monthly, 1),
        longest_dry_spell_days=max(dry_spells) if dry_spells else 0,
        heavy_rain_days_per_season=round(sum(heavy_days) / n_seasons, 1),
        hot_days_per_season=round(sum(hot_days) / n_seasons, 1),
        high_humidity_days_per_season=round(sum(humid_days) / n_seasons, 1),
        mean_t2m=round(mean_t2m, 2),
        mean_t2m_max=round(mean_tmax, 2),
        mean_solar_mj=round(mean_solar, 2),
        mean_rh2m=round(mean_rh, 1),
        mean_gwettop=round(sum(top_all) / len(top_all), 3) if top_all else None,
        mean_gwetroot=round(sum(root_all) / len(root_all), 3) if root_all else None,
    )


class NasaPowerDailyFetcher:
    """Fetches and caches 10-year + recent daily NASA POWER AG data for a point."""

    def __init__(
        self,
        ttl_seconds: int = 3600,
        session: requests.Session | None = None,
        cache_dir: Path | str = Path("data/cache/nasa_power"),
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.session = session or requests.Session()
        self.cache_dir = Path(cache_dir)
        self._cache: dict[tuple[float, float], tuple[float, dict[str, dict[str, float]]]] = {}

    def _disk_cache_path(self, latitude: float, longitude: float, start_str: str, end_str: str) -> Path:
        lat_k = round(latitude, 3)
        lon_k = round(longitude, 3)
        return self.cache_dir / f"{lat_k}_{lon_k}_{start_str}_{end_str}.json"

    def fetch_daily_series(self, latitude: float, longitude: float) -> dict[str, dict[str, float]]:
        key = (round(latitude, 3), round(longitude, 3))
        now = time.monotonic()
        if key in self._cache:
            ts, cached = self._cache[key]
            if now - ts < self.ttl_seconds:
                return cached

        end_dt = date.today() - timedelta(days=3)
        start_dt = date(end_dt.year - 9, 1, 1)
        start_str = start_dt.strftime("%Y%m%d")
        end_str = end_dt.strftime("%Y%m%d")

        cache_path = self._disk_cache_path(latitude, longitude, start_str, end_str)
        if cache_path.exists():
            age = time.time() - cache_path.stat().st_mtime
            if age < self.ttl_seconds:
                param_data = json.loads(cache_path.read_text(encoding="utf-8"))
                self._cache[key] = (now, param_data)
                return param_data

        resp = self.session.get(
            POINT_DAILY_URL,
            params={
                "parameters": DAILY_PARAMS,
                "community": "AG",
                "latitude": latitude,
                "longitude": longitude,
                "start": start_str,
                "end": end_str,
                "format": "JSON",
            },
            timeout=45,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"NASA POWER Point API error {resp.status_code}: {resp.text[:300]}")

        param_data = resp.json()["properties"]["parameter"]
        self._cache[key] = (now, param_data)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(param_data), encoding="utf-8")
        return param_data

    def get_summary(
        self,
        latitude: float,
        longitude: float,
        planting_month: int,
        scenario: str = "historical_average",
    ) -> DailyClimateSummary:
        series = self.fetch_daily_series(latitude, longitude)
        return compute_climate_summary(
            daily_params=series,
            latitude=latitude,
            longitude=longitude,
            planting_month=planting_month,
            scenario=scenario,
        )
