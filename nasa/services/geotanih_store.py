import json
from pathlib import Path
from typing import Any, Dict, Optional, Union

import httpx

from schemas.farm_memory import EvidenceLabel

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
GEOTANIH_ARCGIS_URL = (
    "https://geotanih.doa.gov.my/arcgis/rest/services/Geotanih/SM_SCSC_3/MapServer/0/query"
)


def load_geotanih_context(
    locality_or_lat: Union[str, float, None] = None,
    lon: Optional[float] = None,
    *,
    allow_live: bool = False,
    data_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    base = data_dir or DATA_DIR
    raw = json.loads((base / "geotanih_kedah.json").read_text(encoding="utf-8"))
    matched: Optional[Dict[str, Any]] = None

    if allow_live and isinstance(locality_or_lat, (int, float)) and isinstance(lon, (int, float)):
        try:
            params = {
                "geometry": f"{float(lon)},{float(locality_or_lat)}",
                "geometryType": "esriGeometryPoint",
                "inSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
                "outFields": "*",
                "returnGeometry": "false",
                "f": "json",
            }
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(GEOTANIH_ARCGIS_URL, params=params)
                resp.raise_for_status()
                features = resp.json().get("features", [])
                if features:
                    attrs = features[0].get("attributes", {})
                    soil_cls = str(attrs.get("KELAS") or attrs.get("CLASS") or "2d")
                    flags = ["geotanih_drainage_limitation"] if "d" in soil_cls.lower() else []
                    return {
                        "id": "geotanih_live_arcgis",
                        "state": str(attrs.get("NEGERI") or "Kedah"),
                        "district": str(attrs.get("DAERAH") or "Sungai Petani"),
                        "soil_class": soil_cls,
                        "dominant_texture": "loam",
                        "drainage_tendency": "sometimes_stays_wet" if flags else "drains_well",
                        "limitation_codes": [c for c in ("d", "t", "g", "s") if c in soil_cls.lower()],
                        "limitation_summary_en": f"GeoTanih ArcGIS Soil Class {soil_cls} (live map query).",
                        "limitation_summary_ms": f"Kelas Tanah GeoTanih ArcGIS {soil_cls} (carian peta langsung).",
                        "flags": flags,
                        "evidence_label": EvidenceLabel.ESTIMATED_FROM_MAP,
                        "disclaimer": raw.get("disclaimer", ""),
                    }
        except Exception:
            matched = None

    if isinstance(locality_or_lat, (int, float)) and isinstance(lon, (int, float)):
        lat = float(locality_or_lat)
        lon_f = float(lon)
        for zone in raw.get("zones", []):
            bbox = zone.get("bbox", {})
            if (
                bbox.get("lat_min", -90) <= lat <= bbox.get("lat_max", 90)
                and bbox.get("lon_min", -180) <= lon_f <= bbox.get("lon_max", 180)
            ):
                matched = zone
                break
    elif isinstance(locality_or_lat, str) and locality_or_lat.strip():
        loc_lower = locality_or_lat.lower()
        district_aliases = {
            "sungai petani": "kedah_kuala_muda_sp",
            "kuala muda": "kedah_kuala_muda_sp",
            "langkawi": "kedah_kuala_muda_sp",
            "kota setar": "kedah_kota_setar_mada",
            "kubang pasu": "kedah_kota_setar_mada",
            "pendang": "kedah_kota_setar_mada",
            "yan": "kedah_kota_setar_mada",
            "baling": "kedah_baling_sik_inland",
            "sik": "kedah_baling_sik_inland",
            "padang terap": "kedah_baling_sik_inland",
            "pokok sena": "kedah_baling_sik_inland",
            "kulim": "kedah_baling_sik_inland",
            "bandar baharu": "kedah_baling_sik_inland",
        }
        zones_by_id = {z.get("id"): z for z in raw.get("zones", [])}
        for alias, target_id in district_aliases.items():
            if alias in loc_lower and target_id in zones_by_id:
                matched = dict(zones_by_id[target_id])
                matched["selected_district"] = locality_or_lat.strip()
                break
        if matched is None:
            for zone in raw.get("zones", []):
                state_lower = zone.get("state", "").lower()
                if state_lower and state_lower in loc_lower:
                    matched = zone
                    break

    if matched is not None:
        return {
            **matched,
            "evidence_label": EvidenceLabel.ESTIMATED_FROM_MAP,
            "disclaimer": raw.get("disclaimer", ""),
        }

    default_zone = dict(raw.get("default_zone", {}))
    default_zone["flags"] = []
    return {
        **default_zone,
        "evidence_label": EvidenceLabel.UNKNOWN,
        "disclaimer": raw.get("disclaimer", ""),
    }


def load_market_context(crop_id: str, data_dir: Optional[Path] = None) -> Dict[str, Any]:
    base = data_dir or DATA_DIR
    raw = json.loads((base / "market_prices.json").read_text(encoding="utf-8"))
    crop_entry = raw.get("crops", {}).get(crop_id)
    if not crop_entry:
        return {
            "crop_id": crop_id,
            "unit": "kg",
            "low_myr": None,
            "high_myr": None,
            "volatility": "unknown",
            "trend": "unknown",
            "source": raw.get("source", ""),
            "disclaimer_en": raw.get("disclaimer_en", ""),
            "disclaimer_ms": raw.get("disclaimer_ms", ""),
            "evidence_label": EvidenceLabel.UNKNOWN,
        }
    return {
        "crop_id": crop_id,
        **crop_entry,
        "trend": crop_entry.get("volatility", "stable"),
        "source": raw.get("source", ""),
        "disclaimer_en": raw.get("disclaimer_en", ""),
        "disclaimer_ms": raw.get("disclaimer_ms", ""),
        "evidence_label": EvidenceLabel.HISTORICAL_TREND,
    }
