"""Farm Memory structured record, plain-language question library, and JSON store."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

EvidenceLabel = Literal["verified_by_farmer", "estimated_from_climate_or_map", "unknown"]

QUESTION_LIBRARY: list[dict] = [
    {
        "field": "last_crop",
        "question_en": "What did you plant here last season?",
        "question_ms": "Apakah tanaman anda pada musim lepas?",
        "choices": [
            {"value": "paddy_rice", "label_en": "Paddy (Rice)", "label_ms": "Padi"},
            {"value": "chilli_open_field", "label_en": "Chilli", "label_ms": "Cili"},
            {"value": "sweet_corn", "label_en": "Sweet Corn", "label_ms": "Jagung Manis"},
            {"value": "watermelon", "label_en": "Watermelon", "label_ms": "Tembikai"},
            {"value": "okra", "label_en": "Okra", "label_ms": "Bendi"},
            {"value": "unknown", "label_en": "Not sure / Skip", "label_ms": "Tidak pasti / Langkau"},
        ],
    },
    {
        "field": "irrigation",
        "question_en": "When there is no rain, can you still water this field?",
        "question_ms": "Jika tiada hujan, bolehkah anda masih mengairi ladang ini?",
        "choices": [
            {"value": "always", "label_en": "Always", "label_ms": "Sentiasa boleh"},
            {"value": "sometimes", "label_en": "Sometimes", "label_ms": "Kadang-kadang"},
            {"value": "no", "label_en": "No", "label_ms": "Tiada pengairan"},
            {"value": "unknown", "label_en": "Not sure / Skip", "label_ms": "Tidak pasti / Langkau"},
        ],
    },
    {
        "field": "waterlogging_duration",
        "question_en": "After heavy rain, how long does water stay on the field?",
        "question_ms": "Selepas hujan lebat, berapa lama air bertakung di ladang?",
        "choices": [
            {"value": "same_day", "label_en": "Gone the same day", "label_ms": "Surut hari yang sama"},
            {"value": "one_to_two_days", "label_en": "1 to 2 days", "label_ms": "1 hingga 2 hari"},
            {"value": "more_than_two_days", "label_en": "More than 2 days", "label_ms": "Lebih 2 hari"},
            {"value": "unknown", "label_en": "Not sure / Skip", "label_ms": "Tidak pasti / Langkau"},
        ],
    },
    {
        "field": "flooded_last_season",
        "question_en": "Did this field flood last season?",
        "question_ms": "Adakah ladang ini mengalami banjir pada musim lepas?",
        "choices": [
            {"value": "yes", "label_en": "Yes", "label_ms": "Ya"},
            {"value": "no", "label_en": "No", "label_ms": "Tidak"},
            {"value": "unknown", "label_en": "Not sure / Skip", "label_ms": "Tidak pasti / Langkau"},
        ],
    },
    {
        "field": "soil_feel",
        "question_en": "When the soil is wet, does it feel sticky, loose and sandy, or in-between?",
        "question_ms": "Apabila tanah basah, adakah ia melekit, berpasir, atau sederhana?",
        "choices": [
            {"value": "sticky_clay", "label_en": "Sticky (clay-like)", "label_ms": "Melekit (tanah liat)"},
            {"value": "in_between_loam", "label_en": "In-between (loam)", "label_ms": "Sederhana (lom)"},
            {"value": "loose_sandy", "label_en": "Loose & sandy", "label_ms": "Longgar & berpasir"},
            {"value": "unknown", "label_en": "Not sure / Skip", "label_ms": "Tidak pasti / Langkau"},
        ],
    },
    {
        "field": "soil_ph_known",
        "question_en": "Have you tested the soil pH recently?",
        "question_ms": "Adakah anda pernah menguji pH tanah baru-baru ini?",
        "choices": [
            {"value": "yes_known", "label_en": "Yes, I know the result", "label_ms": "Ya, saya tahu keputusannya"},
            {"value": "no_test", "label_en": "No test", "label_ms": "Tiada ujian"},
            {"value": "unknown", "label_en": "Not sure / Skip", "label_ms": "Tidak pasti / Langkau"},
        ],
    },
    {
        "field": "priority",
        "question_en": "What matters most for your next crop?",
        "question_ms": "Apakah keutamaan anda untuk tanaman seterusnya?",
        "choices": [
            {"value": "lower_risk", "label_en": "Lower risk", "label_ms": "Risiko rendah"},
            {"value": "save_water", "label_en": "Save water", "label_ms": "Jimat air"},
            {"value": "improve_soil", "label_en": "Improve soil", "label_ms": "Baiki tanah"},
            {"value": "earn_more", "label_en": "Earn more", "label_ms": "Pulangan lebih tinggi"},
        ],
    },
    {
        "field": "field_problems",
        "question_en": "What main problem did you notice on this field recently?",
        "question_ms": "Apakah masalah utama yang anda perhatikan di ladang ini baru-baru ini?",
        "choices": [
            {"value": "none", "label_en": "No major problem", "label_ms": "Tiada masalah besar"},
            {"value": "pests_or_disease", "label_en": "Pests or disease", "label_ms": "Perosak atau penyakit"},
            {"value": "weeds", "label_en": "Heavy weeds", "label_ms": "Rumpai tebal"},
            {"value": "poor_growth", "label_en": "Weak or uneven growth", "label_ms": "Pertumbuhan lemah atau tidak sekata"},
            {"value": "unknown", "label_en": "Not sure / Skip", "label_ms": "Tidak pasti / Langkau"},
        ],
    },
    {
        "field": "trouble_spot",
        "question_en": "Is there a specific part of the field that always stays wet or dries out first?",
        "question_ms": "Adakah bahagian tertentu ladang yang sentiasa bertakung air atau cepat kering?",
        "choices": [
            {"value": "none", "label_en": "Field is uniform", "label_ms": "Ladang sekata"},
            {"value": "lower_wet_spot", "label_en": "Lower corner stays wet", "label_ms": "Bahagian rendah sentiasa basah"},
            {"value": "higher_dry_spot", "label_en": "Higher patch dries out fast", "label_ms": "Bahagian tinggi cepat kering"},
            {"value": "unknown", "label_en": "Not sure / Skip", "label_ms": "Tidak pasti / Langkau"},
        ],
    },
    {
        "field": "labour",
        "question_en": "How much labour can you spare for weeding, staking, or frequent harvesting?",
        "question_ms": "Berapa banyak tenaga kerja yang anda ada untuk merumput, memancang, atau menuai kerap?",
        "choices": [
            {"value": "high", "label_en": "Plenty (family/hired help)", "label_ms": "Mencukupi (keluarga/pekerja)"},
            {"value": "moderate", "label_en": "Moderate", "label_ms": "Sederhana"},
            {"value": "limited", "label_en": "Limited (prefer low-care)", "label_ms": "Terhad (utamakan kurang penjagaan)"},
            {"value": "unknown", "label_en": "Not sure / Skip", "label_ms": "Tidak pasti / Langkau"},
        ],
    },
]


class FarmMemoryRecord(BaseModel):
    """Farmer-confirmed field memory record (unknowns allowed and never invented)."""

    farm_id: str = "farm_001"
    locality: str = "Kota Setar (Kampung Teluk Bagan)"
    latitude: float = 6.0704075
    longitude: float = 100.3557400
    last_crop: str = "unknown"
    irrigation: str = "unknown"
    waterlogging_duration: str = "unknown"
    flooded_last_season: str = "unknown"
    soil_feel: str = "unknown"
    soil_ph_known: str = "unknown"
    priority: str = "lower_risk"
    field_problems: str = "unknown"
    trouble_spot: str = "unknown"
    labour: str = "unknown"
    field_observations: list[dict[str, str]] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    def evidence_summary(self) -> tuple[list[str], list[str]]:
        """Return (known_fields, unknown_fields) without treating unknown as negative."""
        known: list[str] = ["NASA POWER daily rainfall, temperature, sunlight & humidity"]
        unknown: list[str] = []

        field_labels = {
            "last_crop": "previous crop history",
            "irrigation": "irrigation availability",
            "waterlogging_duration": "field drainage / standing water",
            "flooded_last_season": "recent flood history",
            "soil_feel": "soil texture feel",
            "soil_ph_known": "recent soil pH test",
            "field_problems": "recent field problems",
            "trouble_spot": "field trouble spot",
            "labour": "available labour",
        }
        for attr, label in field_labels.items():
            val = getattr(self, attr, "unknown")
            if val in ("unknown", "no_test", "", None):
                unknown.append(label)
            else:
                known.append(f"{label} (verified by farmer)")

        return known, unknown


class FarmMemoryStore:
    """Simple JSON file store for farmer-confirmed Farm Memory records."""

    def __init__(self, base_dir: Path | str = Path("data/farm_memory")) -> None:
        self.base_dir = Path(base_dir)

    def _path(self, farm_id: str) -> Path:
        safe_id = "".join(c for c in farm_id if c.isalnum() or c in ("-", "_")) or "farm_001"
        return self.base_dir / f"{safe_id}.json"

    def get(self, farm_id: str) -> FarmMemoryRecord | None:
        path = self._path(farm_id)
        if not path.exists():
            return None
        return FarmMemoryRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, record: FarmMemoryRecord) -> FarmMemoryRecord:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        record.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._path(record.farm_id).write_text(record.model_dump_json(indent=2), encoding="utf-8")
        return record

    def delete(self, farm_id: str) -> bool:
        path = self._path(farm_id)
        if path.exists():
            path.unlink()
            return True
        return False


def next_useful_question(
    memory: FarmMemoryRecord,
    geotanih: dict[str, Any] | None = None,
    target_crop: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return the highest-priority unanswered question, prioritizing waterlogging when relevant."""
    by_field = {q["field"]: q for q in QUESTION_LIBRARY}

    if memory.waterlogging_duration == "unknown":
        poor_geotanih = (geotanih or {}).get("drainage_class") in {"poor", "imperfect"}
        flood_sensitive_crop = (target_crop or {}).get("flood_tolerance") == "low"
        if memory.flooded_last_season == "yes" or poor_geotanih or flood_sensitive_crop:
            return by_field["waterlogging_duration"]

    for question in QUESTION_LIBRARY:
        val = getattr(memory, question["field"], "unknown")
        if val in ("unknown", "", None):
            return question
    return None
