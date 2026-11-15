import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from schemas import (
    CropHistoryEntry,
    EvidenceLabel,
    FarmLocation,
    FarmMemory,
    FieldObservation,
    IrrigationAvailability,
    PendingConfirmation,
    SoilFeel,
    SoilTestStatus,
    TrackedValue,
    WaterloggingDuration,
)


class MemoryStore:
    """Persistent JSON-backed FarmMemory and pending-confirmation store."""

    def __init__(
        self,
        storage_dir: Path | str | None = None,
        *,
        base_dir: Path | str | None = None,
    ) -> None:
        resolved = base_dir if base_dir is not None else storage_dir
        self.storage_dir = (
            Path(resolved)
            if resolved is not None
            else (Path(__file__).resolve().parents[1] / "data" / "farm_memories")
        )
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._farms: dict[str, FarmMemory] = {}
        self._pending: dict[str, PendingConfirmation] = {}

    def _farm_path(self, farm_id: str) -> Path:
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", farm_id)
        return self.storage_dir / f"{safe_id}.json"

    def _save_farm(self, farm: FarmMemory) -> None:
        path = self._farm_path(farm.farm_id)
        path.write_text(farm.model_dump_json(indent=2), encoding="utf-8")

    def get_or_create_farm(
        self,
        farm_id: str,
        user_id: Optional[str] = None,
        access_token: Optional[str] = None,
    ) -> FarmMemory:
        if farm_id in self._farms:
            return self._farms[farm_id]

        path = self._farm_path(farm_id)
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            farm = FarmMemory.model_validate(raw)
        else:
            farm = FarmMemory(farm_id=farm_id)
            self._save_farm(farm)

        self._farms[farm_id] = farm
        return farm

    def get_farm(self, farm_id: str) -> Optional[FarmMemory]:
        if farm_id in self._farms:
            return self._farms[farm_id]
        path = self._farm_path(farm_id)
        if path.exists():
            return self.get_or_create_farm(farm_id)
        return None

    def list_farms(
        self,
        user_id: Optional[str] = None,
        access_token: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        files = sorted(self.storage_dir.glob("*.json"))
        if not files:
            default_farm = self.get_or_create_farm("farm_001")
            return [{"farm_id": default_farm.farm_id, "farm_name": "Farm 001", "locality": default_farm.location.locality}]
        farms: list[dict[str, Any]] = []
        for path in files:
            try:
                farm = FarmMemory.model_validate_json(path.read_text(encoding="utf-8"))
                farms.append({
                    "farm_id": farm.farm_id,
                    "farm_name": farm.farm_id.replace("_", " ").title(),
                    "locality": farm.location.locality,
                })
            except Exception:
                continue
        if not farms:
            default_farm = self.get_or_create_farm("farm_001")
            return [{"farm_id": default_farm.farm_id, "farm_name": "Farm 001", "locality": default_farm.location.locality}]
        return farms

    def sync_farm_memory(
        self,
        farm_id: str,
        incoming: FarmMemory,
        user_id: Optional[str] = None,
        access_token: Optional[str] = None,
    ) -> FarmMemory:
        """Restore or merge a device-local FarmMemory snapshot so server/AI match the device."""
        path = self._farm_path(farm_id)
        had_saved = path.exists() or (farm_id in self._farms)
        normalized = incoming.model_copy(update={"farm_id": farm_id})

        if not had_saved:
            self._farms[farm_id] = normalized
            self._save_farm(normalized)
            return normalized

        current = self.get_or_create_farm(farm_id)

        def _pick_tracked(cur_tv: TrackedValue[Any], inc_tv: TrackedValue[Any]) -> TrackedValue[Any]:
            cur_known = cur_tv.evidence_label != EvidenceLabel.UNKNOWN
            inc_known = inc_tv.evidence_label != EvidenceLabel.UNKNOWN
            if inc_known and not cur_known:
                return inc_tv
            if cur_known and not inc_known:
                return cur_tv
            if inc_known and cur_known:
                cur_dt = cur_tv.confirmed_at or datetime.min.replace(tzinfo=timezone.utc)
                inc_dt = inc_tv.confirmed_at or datetime.min.replace(tzinfo=timezone.utc)
                if cur_dt.tzinfo is None:
                    cur_dt = cur_dt.replace(tzinfo=timezone.utc)
                if inc_dt.tzinfo is None:
                    inc_dt = inc_dt.replace(tzinfo=timezone.utc)
                return inc_tv if inc_dt >= cur_dt else cur_tv
            return cur_tv

        current.irrigation_availability = _pick_tracked(
            current.irrigation_availability, normalized.irrigation_availability
        )
        current.labour_availability = _pick_tracked(
            current.labour_availability, normalized.labour_availability
        )
        current.soil.texture_feel = _pick_tracked(current.soil.texture_feel, normalized.soil.texture_feel)
        current.soil.waterlogging_duration = _pick_tracked(
            current.soil.waterlogging_duration, normalized.soil.waterlogging_duration
        )
        current.soil.flooded_last_season = _pick_tracked(
            current.soil.flooded_last_season, normalized.soil.flooded_last_season
        )
        current.soil.ph = _pick_tracked(current.soil.ph, normalized.soil.ph)
        current.soil.soil_test_status = _pick_tracked(
            current.soil.soil_test_status, normalized.soil.soil_test_status
        )
        current.soil.trouble_spot = _pick_tracked(current.soil.trouble_spot, normalized.soil.trouble_spot)

        if normalized.location.latitude is not None and current.location.latitude is None:
            current.location = normalized.location

        seen_crops = {(c.season.lower(), c.raw_crop_name.lower()) for c in current.crop_history}
        for c in normalized.crop_history:
            key = (c.season.lower(), c.raw_crop_name.lower())
            if key not in seen_crops:
                seen_crops.add(key)
                current.crop_history.append(c)

        seen_obs = {
            (o.zone.lower(), o.event_type.lower(), o.observation.lower())
            for o in current.field_observations
        }
        for o in normalized.field_observations:
            key = (o.zone.lower(), o.event_type.lower(), o.observation.lower())
            if key not in seen_obs:
                seen_obs.add(key)
                current.field_observations.append(o)

        self._farms[farm_id] = current
        self._save_farm(current)
        return current

    def update_location(
        self,
        farm_id: str,
        locality: str,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        user_id: Optional[str] = None,
        access_token: Optional[str] = None,
    ) -> FarmMemory:
        farm = self.get_or_create_farm(farm_id)
        farm.location = FarmLocation(locality=locality, latitude=latitude, longitude=longitude)
        self._save_farm(farm)
        return farm

    def save_rotation_comparison(
        self,
        farm_id: str,
        result: dict[str, Any],
        user_id: Optional[str] = None,
        access_token: Optional[str] = None,
    ) -> None:
        return None

    def delete_farm(
        self,
        farm_id: str,
        user_id: Optional[str] = None,
        access_token: Optional[str] = None,
    ) -> bool:
        existed = self._farms.pop(farm_id, None) is not None
        path = self._farm_path(farm_id)
        if path.exists():
            path.unlink()
            existed = True
        return existed

    def save_pending(self, session_id: str, confirmation: PendingConfirmation) -> None:
        self._pending[f"{session_id}:{confirmation.confirmation_id}"] = confirmation

    def pop_pending(self, session_id: str, confirmation_id: str) -> Optional[PendingConfirmation]:
        return self._pending.pop(f"{session_id}:{confirmation_id}", None)

    def apply_confirmed_fact(
        self,
        farm_id: str,
        target_field: str,
        value: Any,
        user_id: Optional[str] = None,
        access_token: Optional[str] = None,
    ) -> FarmMemory:
        """Persist a farmer-confirmed fact into FarmMemory and flush to disk."""
        farm = self.get_or_create_farm(farm_id)
        now = datetime.now(timezone.utc)
        raw_val = "unknown" if value in (None, "unknown", "skip") else str(value)
        evidence = (
            EvidenceLabel.UNKNOWN
            if raw_val == "unknown"
            else EvidenceLabel.VERIFIED_BY_FARMER
        )

        if target_field == "irrigation_availability":
            farm.irrigation_availability = TrackedValue(
                value=IrrigationAvailability(raw_val),
                evidence_label=evidence,
                confirmed_at=now,
                source="farmer_voice_confirmed",
            )
        elif target_field == "labour_availability":
            farm.labour_availability = TrackedValue(
                value=raw_val,
                evidence_label=evidence,
                confirmed_at=now,
                source="farmer_voice_confirmed",
            )
        elif target_field == "soil.waterlogging_duration":
            farm.soil.waterlogging_duration = TrackedValue(
                value=WaterloggingDuration(raw_val),
                evidence_label=evidence,
                confirmed_at=now,
                source="farmer_voice_confirmed",
            )
        elif target_field == "soil.texture_feel":
            farm.soil.texture_feel = TrackedValue(
                value=SoilFeel(raw_val),
                evidence_label=evidence,
                confirmed_at=now,
                source="farmer_voice_confirmed",
            )
        elif target_field == "soil.soil_test_status":
            farm.soil.soil_test_status = TrackedValue(
                value=SoilTestStatus(raw_val),
                evidence_label=evidence,
                confirmed_at=now,
                source="farmer_voice_confirmed",
            )
        elif target_field == "soil.ph":
            parsed_ph: Optional[float] = None
            if raw_val != "unknown":
                try:
                    parsed_ph = float(raw_val)
                except (TypeError, ValueError):
                    parsed_ph = None
            farm.soil.ph = TrackedValue(
                value=parsed_ph,
                evidence_label=(EvidenceLabel.VERIFIED_BY_FARMER if parsed_ph is not None else EvidenceLabel.UNKNOWN),
                confirmed_at=now,
                source="farmer_voice_confirmed",
            )
        elif target_field in ("soil.flooded_last_season", "soil.trouble_spot"):
            attr = target_field.split(".")[1]
            setattr(
                farm.soil,
                attr,
                TrackedValue(
                    value=raw_val,
                    evidence_label=evidence,
                    confirmed_at=now,
                    source="farmer_voice_confirmed",
                ),
            )
        elif target_field == "priorities":
            key = str(value)
            if hasattr(farm.priorities, key):
                setattr(farm.priorities, key, 3)
        elif target_field == "crop_history":
            crop_id = value.get("crop_id") if isinstance(value, dict) else None
            raw_name = value.get("raw_crop_name", str(value)) if isinstance(value, dict) else str(value)
            farm.crop_history.append(
                CropHistoryEntry(
                    season="previous_season",
                    crop_id=crop_id,
                    raw_crop_name=raw_name,
                    evidence_label=evidence,
                    confirmed_at=now,
                )
            )
        elif target_field == "field_observations":
            if isinstance(value, dict):
                farm.field_observations.append(
                    FieldObservation(
                        zone=value.get("zone") or "general",
                        event_type=value.get("event_type") or "general",
                        affected_crop=value.get("affected_crop"),
                        timing_or_duration=value.get("timing_or_duration"),
                        observation=value.get("observation") or str(value),
                        evidence_label=evidence,
                        source="farmer-confirmed",
                        recorded_at=now,
                    )
                )
            else:
                farm.field_observations.append(
                    FieldObservation(
                        observation=str(value),
                        evidence_label=evidence,
                        source="farmer-confirmed",
                        recorded_at=now,
                    )
                )

        self._save_farm(farm)
        return farm
