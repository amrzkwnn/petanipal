"""Local GeoTanih soil and FAMA AMI market context loaders."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_GEOTANIH_PATH = Path(__file__).resolve().parents[3] / "data" / "geotanih_kedah.json"
DEFAULT_MARKET_PATH = Path(__file__).resolve().parents[3] / "data" / "market_prices.json"


def load_geotanih_context(
    district_name: str,
    path: Path = DEFAULT_GEOTANIH_PATH,
) -> dict[str, Any]:
    """Return GeoTanih soil context for a Kedah district, or an explicit unknown fallback."""
    if not district_name or not path.exists():
        return _unknown_geotanih(district_name)

    data = json.loads(path.read_text(encoding="utf-8"))
    districts: dict[str, dict[str, Any]] = data.get("districts", {})
    normalized = district_name.strip().lower()
    matched_name = next((name for name in districts if name.lower() == normalized), None)
    if matched_name is None:
        return _unknown_geotanih(district_name)

    entry = districts[matched_name]
    return {
        "district": matched_name,
        "soil_series": entry["soil_series"],
        "texture": entry["texture"],
        "drainage_class": entry["drainage_class"],
        "slope_limitation": entry["slope_limitation"],
        "source_name": data.get("source_name", "GeoTanih"),
        "source_url": data.get("source_url", "https://geotanih.doa.gov.my/"),
        "last_reviewed": data.get("last_reviewed", "unknown"),
        "evidence_label": "estimated_from_climate_or_map",
    }


def load_market_context(
    crop_id: str,
    path: Path = DEFAULT_MARKET_PATH,
) -> dict[str, Any]:
    """Return recent FAMA AMI market context for a crop, or an explicit unknown fallback."""
    if not crop_id or not path.exists():
        return _unknown_market(crop_id)

    data = json.loads(path.read_text(encoding="utf-8"))
    crops: dict[str, dict[str, Any]] = data.get("crops", {})
    entry = crops.get(crop_id)
    if entry is None:
        return _unknown_market(crop_id)

    return {
        "crop_id": crop_id,
        "trend": entry["trend"],
        "price_band_rm_per_kg": entry["price_band_rm_per_kg"],
        "note_en": entry["note_en"],
        "note_ms": entry["note_ms"],
        "last_updated": data.get("last_updated", "unknown"),
        "source_name": data.get("source_name", "FAMA AMI"),
        "source_url": data.get("source_url", "https://www.fama.gov.my/"),
        "disclaimer_en": data.get(
            "disclaimer_en",
            "This is recent FAMA AMI context, not a future-price promise.",
        ),
        "disclaimer_ms": data.get(
            "disclaimer_ms",
            "Ini ialah konteks pasaran terkini FAMA AMI, bukan jaminan harga masa hadapan.",
        ),
        "evidence_label": "estimated_from_climate_or_map",
    }


def _unknown_geotanih(district_name: str) -> dict[str, Any]:
    return {
        "district": district_name or "unknown",
        "soil_series": "unknown",
        "texture": "unknown",
        "drainage_class": "unknown",
        "slope_limitation": "unknown",
        "source_name": "GeoTanih",
        "source_url": "https://geotanih.doa.gov.my/",
        "last_reviewed": "unknown",
        "evidence_label": "unknown",
    }


def _unknown_market(crop_id: str) -> dict[str, Any]:
    return {
        "crop_id": crop_id or "unknown",
        "trend": "unknown",
        "price_band_rm_per_kg": [],
        "note_en": "No recent FAMA AMI entry for this crop.",
        "note_ms": "Tiada rekod FAMA AMI terkini untuk tanaman ini.",
        "last_updated": "unknown",
        "source_name": "FAMA AMI",
        "source_url": "https://www.fama.gov.my/",
        "disclaimer_en": "This is recent FAMA AMI context, not a future-price promise.",
        "disclaimer_ms": "Ini ialah konteks pasaran terkini FAMA AMI, bukan jaminan harga masa hadapan.",
        "evidence_label": "unknown",
    }
