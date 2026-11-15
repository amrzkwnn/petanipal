"""Client for the NASA POWER Regional REST API."""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from .presets import BoundingBox

BASE_URL = "https://power.larc.nasa.gov/api/temporal"
TEMPORAL_SCALES = ("daily", "hourly", "monthly", "climatology")
COMMUNITIES = ("RE", "AG", "SB")
OUTPUT_FORMATS = ("CSV", "JSON", "NETCDF", "GEOJSON")
MAX_PARAMETERS_PER_REQUEST = 1
FILL_VALUE = -999


class NasaPowerApiError(RuntimeError):
    """Raised when the NASA POWER API returns an error or invalid payload."""


def _normalize_parameters(parameters: str | Sequence[str], max_count: int | None = None) -> list[str]:
    if isinstance(parameters, str):
        items = [p.strip() for p in parameters.split(",") if p.strip()]
    else:
        items = [str(p).strip() for p in parameters if str(p).strip()]

    if not items:
        raise ValueError("At least one parameter must be specified.")
    if max_count is not None and len(items) > max_count:
        raise ValueError(
            f"NASA POWER Regional API supports at most {max_count} parameter per raw request "
            f"(got {len(items)}). Use fetch_dataframe() or --tidy to fetch multiple parameters."
        )
    return items


def _extract_feature_lat_lon(geometry: dict[str, Any]) -> tuple[float | None, float | None]:
    """Extract representative (latitude, longitude) from a GeoJSON geometry."""
    geom_type = geometry.get("type")
    coords = geometry.get("coordinates")
    if not coords:
        return None, None

    if geom_type == "Point" and len(coords) >= 2:
        return float(coords[1]), float(coords[0])

    if geom_type == "Polygon" and coords[0]:
        ring = coords[0]
        lons = [pt[0] for pt in ring]
        lats = [pt[1] for pt in ring]
        return sum(lats) / len(lats), sum(lons) / len(lons)

    return None, None


def _clean_value(value: Any) -> Any:
    if isinstance(value, (int, float)) and math.isclose(float(value), FILL_VALUE, abs_tol=1e-6):
        return float("nan")
    return value


def parse_regional_json_to_dataframe(payload: dict[str, Any]) -> pd.DataFrame:
    """Flatten a NASA POWER regional JSON/GeoJSON response into a tidy DataFrame."""
    if payload.get("type") == "FeatureCollection":
        features = payload.get("features", [])
    elif "properties" in payload:
        features = [payload]
    else:
        raise NasaPowerApiError("Unexpected JSON payload structure from NASA POWER API.")

    rows_by_key: dict[tuple[float | None, float | None, str], dict[str, Any]] = {}

    for feature in features:
        lat, lon = _extract_feature_lat_lon(feature.get("geometry") or {})
        param_map = (feature.get("properties") or {}).get("parameter") or {}

        for param_name, date_series in param_map.items():
            if not isinstance(date_series, dict):
                continue
            for date_key, raw_val in date_series.items():
                row_key = (lat, lon, str(date_key))
                row = rows_by_key.setdefault(
                    row_key,
                    {"latitude": lat, "longitude": lon, "date": str(date_key)},
                )
                row[param_name] = _clean_value(raw_val)

    if not rows_by_key:
        return pd.DataFrame(columns=["latitude", "longitude", "date"])

    df = pd.DataFrame(rows_by_key.values())
    sort_cols = [c for c in ("date", "latitude", "longitude") if c in df.columns]
    return df.sort_values(sort_cols, na_position="last").reset_index(drop=True)


class NasaPowerRegionalClient:
    """HTTP client for querying NASA POWER regional bounding-box endpoints."""

    def __init__(
        self,
        base_url: str = BASE_URL,
        timeout: int = 60,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()

    def build_url(self, temporal: str) -> str:
        """Build the regional endpoint URL for a given temporal resolution."""
        scale = temporal.lower()
        if scale not in TEMPORAL_SCALES:
            raise ValueError(
                f"Unsupported temporal scale '{temporal}'. "
                f"Choose from: {', '.join(TEMPORAL_SCALES)}."
            )
        return f"{self.base_url}/{scale}/regional"

    def build_params(
        self,
        bbox: BoundingBox,
        parameters: str | Sequence[str],
        temporal: str = "daily",
        community: str = "RE",
        start: str | None = None,
        end: str | None = None,
        output_format: str = "JSON",
    ) -> dict[str, Any]:
        """Validate and assemble query parameters for a regional request."""
        scale = temporal.lower()
        if scale not in TEMPORAL_SCALES:
            raise ValueError(
                f"Unsupported temporal scale '{temporal}'. "
                f"Choose from: {', '.join(TEMPORAL_SCALES)}."
            )

        comm = community.upper()
        if comm not in COMMUNITIES:
            raise ValueError(
                f"Unsupported community '{community}'. "
                f"Choose from: {', '.join(COMMUNITIES)}."
            )

        fmt = output_format.upper()
        if fmt not in OUTPUT_FORMATS:
            raise ValueError(
                f"Unsupported format '{output_format}'. "
                f"Choose from: {', '.join(OUTPUT_FORMATS)}."
            )

        if scale != "climatology" and (not start or not end):
            raise ValueError(f"'start' and 'end' are required for '{scale}' queries.")

        param_list = _normalize_parameters(parameters, max_count=MAX_PARAMETERS_PER_REQUEST)

        query: dict[str, Any] = {
            "parameters": ",".join(param_list),
            "community": comm,
            "latitude-min": bbox.lat_min,
            "latitude-max": bbox.lat_max,
            "longitude-min": bbox.lon_min,
            "longitude-max": bbox.lon_max,
            "format": fmt,
        }
        if start:
            query["start"] = start
        if end:
            query["end"] = end

        return query

    def fetch_raw(
        self,
        bbox: BoundingBox,
        parameters: str | Sequence[str],
        temporal: str = "daily",
        community: str = "RE",
        start: str | None = None,
        end: str | None = None,
        output_format: str = "JSON",
    ) -> bytes | dict[str, Any]:
        """Execute the regional API request and return parsed JSON or raw bytes."""
        url = self.build_url(temporal)
        params = self.build_params(
            bbox=bbox,
            parameters=parameters,
            temporal=temporal,
            community=community,
            start=start,
            end=end,
            output_format=output_format,
        )

        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise NasaPowerApiError(f"Request to NASA POWER API failed: {exc}") from exc

        if response.status_code != 200:
            raise NasaPowerApiError(
                f"NASA POWER API error {response.status_code}: {response.text[:500]}"
            )

        if params["format"] in ("JSON", "GEOJSON"):
            try:
                return response.json()
            except ValueError as exc:
                raise NasaPowerApiError("Failed to decode JSON response.") from exc

        return response.content

    def fetch_dataframe(
        self,
        bbox: BoundingBox,
        parameters: str | Sequence[str],
        temporal: str = "daily",
        community: str = "RE",
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        """Fetch regional data as JSON and return it as a tidy pandas DataFrame.

        Multiple parameters are fetched sequentially (one per API request due to
        NASA POWER Regional's 1-parameter-per-request limit) and merged on
        (latitude, longitude, date).
        """
        param_list = _normalize_parameters(parameters)
        merged: pd.DataFrame | None = None

        for param in param_list:
            payload = self.fetch_raw(
                bbox=bbox,
                parameters=param,
                temporal=temporal,
                community=community,
                start=start,
                end=end,
                output_format="JSON",
            )
            if not isinstance(payload, dict):
                raise NasaPowerApiError("Expected JSON dictionary payload.")

            df_part = parse_regional_json_to_dataframe(payload)
            if merged is None:
                merged = df_part
            else:
                merged = pd.merge(
                    merged,
                    df_part,
                    on=["latitude", "longitude", "date"],
                    how="outer",
                )

        if merged is None:
            return pd.DataFrame(columns=["latitude", "longitude", "date"])

        sort_cols = [c for c in ("date", "latitude", "longitude") if c in merged.columns]
        return merged.sort_values(sort_cols, na_position="last").reset_index(drop=True)

    def download(
        self,
        output_path: str | Path,
        bbox: BoundingBox,
        parameters: str | Sequence[str],
        temporal: str = "daily",
        community: str = "RE",
        start: str | None = None,
        end: str | None = None,
        output_format: str = "CSV",
    ) -> Path:
        """Download regional data directly from NASA POWER and save to disk."""
        dest = Path(output_path)
        dest.parent.mkdir(parents=True, exist_ok=True)

        data = self.fetch_raw(
            bbox=bbox,
            parameters=parameters,
            temporal=temporal,
            community=community,
            start=start,
            end=end,
            output_format=output_format,
        )

        if isinstance(data, dict):
            dest.write_text(json.dumps(data, indent=2), encoding="utf-8")
        else:
            dest.write_bytes(data)

        return dest
