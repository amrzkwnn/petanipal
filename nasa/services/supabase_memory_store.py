import importlib
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import HTTPException

from schemas import (
    CropHistoryEntry,
    EvidenceLabel,
    FarmLocation,
    FarmMemory,
    FieldObservation,
    IrrigationAvailability,
    LanguageCode,
    PendingConfirmation,
    Priorities,
    SoilContext,
    SoilFeel,
    SoilTestStatus,
    TrackedValue,
    WaterloggingDuration,
)


def _create_supabase_client(url: str, key: str) -> Any:
    """Import supabase SDK without shadowing from nasa/supabase/ directory."""
    nasa_dir = str(Path(__file__).resolve().parents[1])
    orig_path = list(sys.path)
    try:
        sys.path = [p for p in sys.path if Path(p or ".").resolve() != Path(nasa_dir)]
        if "supabase" in sys.modules and not hasattr(sys.modules["supabase"], "create_client"):
            del sys.modules["supabase"]
        mod = importlib.import_module("supabase")
        return mod.create_client(url, key)
    finally:
        sys.path = orig_path


class SupabaseMemoryStore:
    """Supabase Postgres + Auth backed FarmMemory store with RLS enforcement."""

    def __init__(self) -> None:
        self.url = os.environ["SUPABASE_URL"]
        self.key = os.environ["SUPABASE_KEY"]
        self._pending: dict[str, PendingConfirmation] = {}

    def _client_for_token(self, access_token: str) -> Any:
        client = _create_supabase_client(self.url, self.key)
        client.postgrest.auth(access_token)
        return client

    @staticmethod
    def _is_valid_uuid(value: str) -> bool:
        try:
            uuid.UUID(str(value))
            return True
        except (ValueError, TypeError, AttributeError):
            return False

    def verify_user(self, access_token: str) -> str:
        """Verify Supabase JWT and return user_id (auto-creates profile on first login)."""
        client = _create_supabase_client(self.url, self.key)
        try:
            res = client.auth.get_user(access_token)
        except Exception as exc:
            raise HTTPException(status_code=401, detail="Invalid or expired Supabase token.") from exc
        if not res or not res.user:
            raise HTTPException(status_code=401, detail="Invalid or expired Supabase token.")
        user_id = str(res.user.id)

        authed = self._client_for_token(access_token)
        existing = authed.table("profiles").select("id").eq("id", user_id).execute()
        if not existing.data:
            authed.table("profiles").insert({"id": user_id, "preferred_language": "ms"}).execute()
        return user_id

    def save_pending(self, session_id: str, confirmation: PendingConfirmation) -> None:
        self._pending[f"{session_id}:{confirmation.confirmation_id}"] = confirmation

    def pop_pending(self, session_id: str, confirmation_id: str) -> Optional[PendingConfirmation]:
        return self._pending.pop(f"{session_id}:{confirmation_id}", None)

    @staticmethod
    def _row_to_farm_memory(
        row: dict[str, Any],
        crop_rows: list[dict[str, Any]],
        obs_rows: list[dict[str, Any]],
        preferred_language: LanguageCode = LanguageCode.MS,
    ) -> FarmMemory:
        soil_data = row.get("soil") or {}
        return FarmMemory(
            farm_id=str(row["id"]),
            preferred_language=preferred_language,
            location=FarmLocation(
                locality=row.get("locality") or "Sungai Petani, Kedah",
                latitude=row.get("latitude"),
                longitude=row.get("longitude"),
            ),
            irrigation_availability=TrackedValue[IrrigationAvailability].model_validate(
                row.get("irrigation_availability") or {"value": "unknown", "evidence_label": "unknown"}
            ),
            labour_availability=TrackedValue[str].model_validate(
                row.get("labour_availability") or {"value": "unknown", "evidence_label": "unknown"}
            ),
            soil=SoilContext(
                texture_feel=TrackedValue[SoilFeel].model_validate(
                    soil_data.get("texture_feel") or {"value": "unknown", "evidence_label": "unknown"}
                ),
                waterlogging_duration=TrackedValue[WaterloggingDuration].model_validate(
                    soil_data.get("waterlogging_duration") or {"value": "unknown", "evidence_label": "unknown"}
                ),
                flooded_last_season=TrackedValue[str].model_validate(
                    soil_data.get("flooded_last_season") or {"value": "unknown", "evidence_label": "unknown"}
                ),
                ph=TrackedValue[float].model_validate(
                    soil_data.get("ph") or {"value": None, "evidence_label": "unknown"}
                ),
                soil_test_status=TrackedValue[SoilTestStatus].model_validate(
                    soil_data.get("soil_test_status") or {"value": "unknown", "evidence_label": "unknown"}
                ),
                trouble_spot=TrackedValue[str].model_validate(
                    soil_data.get("trouble_spot") or {"value": "unknown", "evidence_label": "unknown"}
                ),
            ),
            priorities=Priorities.model_validate(row.get("priorities") or {}),
            crop_history=[
                CropHistoryEntry(
                    season=c["season"],
                    crop_id=c.get("crop_id"),
                    raw_crop_name=c["raw_crop_name"],
                    issue=c.get("issue"),
                    evidence_label=EvidenceLabel(c.get("evidence_label", "verified_by_farmer")),
                    confirmed_at=c.get("confirmed_at"),
                )
                for c in crop_rows
            ],
            field_observations=[
                FieldObservation(
                    zone=o.get("zone", "general"),
                    event_type=o.get("event_type", "general"),
                    affected_crop=o.get("affected_crop"),
                    timing_or_duration=o.get("timing_or_duration"),
                    observation=o["observation"],
                    evidence_label=EvidenceLabel(o.get("evidence_label", "verified_by_farmer")),
                    source=o.get("source", "farmer-confirmed"),
                    recorded_at=o["recorded_at"],
                )
                for o in obs_rows
            ],
        )

    def get_or_create_farm(
        self,
        farm_id: str,
        user_id: Optional[str] = None,
        access_token: Optional[str] = None,
    ) -> FarmMemory:
        if not user_id or not access_token:
            raise HTTPException(status_code=401, detail="Authentication required.")

        client = self._client_for_token(access_token)
        row: Optional[dict[str, Any]] = None

        if self._is_valid_uuid(farm_id):
            res = client.table("farms").select("*").eq("id", farm_id).eq("user_id", user_id).execute()
            if res.data:
                row = res.data[0]

        if row is None and farm_id != "new":
            res = client.table("farms").select("*").eq("user_id", user_id).limit(1).execute()
            if res.data:
                row = res.data[0]

        if row is None:
            insert_payload: dict[str, Any] = {"user_id": user_id, "locality": "Sungai Petani, Kedah"}
            if farm_id not in ("default", "new") and not self._is_valid_uuid(farm_id):
                insert_payload["farm_name"] = farm_id.replace("_", " ").title()
            inserted = client.table("farms").insert(insert_payload).execute()
            row = inserted.data[0]

        real_farm_id = str(row["id"])
        crops_res = client.table("crop_history").select("*").eq("farm_id", real_farm_id).execute()
        obs_res = (
            client.table("field_observations")
            .select("*")
            .eq("farm_id", real_farm_id)
            .order("recorded_at")
            .execute()
        )
        return self._row_to_farm_memory(row, crops_res.data or [], obs_res.data or [])

    def delete_farm(
        self,
        farm_id: str,
        user_id: Optional[str] = None,
        access_token: Optional[str] = None,
    ) -> bool:
        if not user_id or not access_token:
            raise HTTPException(status_code=401, detail="Authentication required.")
        if not self._is_valid_uuid(farm_id):
            return False
        client = self._client_for_token(access_token)
        res = client.table("farms").delete().eq("id", farm_id).eq("user_id", user_id).execute()
        return bool(res.data)

    def list_farms(
        self,
        user_id: Optional[str] = None,
        access_token: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        if not user_id or not access_token:
            raise HTTPException(status_code=401, detail="Authentication required.")
        client = self._client_for_token(access_token)
        res = client.table("farms").select("id,farm_name,locality").eq("user_id", user_id).execute()
        rows = res.data or []
        if not rows:
            default_farm = self.get_or_create_farm("default", user_id=user_id, access_token=access_token)
            return [{"farm_id": default_farm.farm_id, "farm_name": "My Farm", "locality": default_farm.location.locality}]
        return [
            {
                "farm_id": str(r["id"]),
                "farm_name": r.get("farm_name") or "My Farm",
                "locality": r.get("locality") or "Sungai Petani, Kedah",
            }
            for r in rows
        ]

    def update_location(
        self,
        farm_id: str,
        locality: str,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        user_id: Optional[str] = None,
        access_token: Optional[str] = None,
    ) -> FarmMemory:
        if not user_id or not access_token:
            raise HTTPException(status_code=401, detail="Authentication required.")
        farm = self.get_or_create_farm(farm_id, user_id=user_id, access_token=access_token)
        real_farm_id = farm.farm_id
        client = self._client_for_token(access_token)
        now = datetime.now(timezone.utc).isoformat()
        client.table("farms").update(
            {"locality": locality, "latitude": latitude, "longitude": longitude, "updated_at": now}
        ).eq("id", real_farm_id).eq("user_id", user_id).execute()
        return self.get_or_create_farm(real_farm_id, user_id=user_id, access_token=access_token)

    def save_rotation_comparison(
        self,
        farm_id: str,
        result: dict[str, Any],
        user_id: Optional[str] = None,
        access_token: Optional[str] = None,
    ) -> None:
        if not user_id or not access_token:
            return None
        try:
            farm = self.get_or_create_farm(farm_id, user_id=user_id, access_token=access_token)
            client = self._client_for_token(access_token)
            client.table("rotation_comparisons").insert(
                {
                    "farm_id": farm.farm_id,
                    "user_id": user_id,
                    "options": result.get("options") or result.get("rotations", []),
                    "answer_basis": result.get("answer_basis", []),
                    "missing_info": result.get("missing_info", []),
                }
            ).execute()
        except Exception:
            return None

    def apply_confirmed_fact(
        self,
        farm_id: str,
        target_field: str,
        value: Any,
        user_id: Optional[str] = None,
        access_token: Optional[str] = None,
    ) -> FarmMemory:
        if not user_id or not access_token:
            raise HTTPException(status_code=401, detail="Authentication required.")

        farm = self.get_or_create_farm(farm_id, user_id=user_id, access_token=access_token)
        real_farm_id = farm.farm_id
        client = self._client_for_token(access_token)
        now = datetime.now(timezone.utc).isoformat()
        raw_val = "unknown" if value in (None, "unknown", "skip") else str(value)
        evidence = "unknown" if raw_val == "unknown" else "verified_by_farmer"

        if target_field == "irrigation_availability":
            payload = {
                "value": raw_val,
                "evidence_label": evidence,
                "confirmed_at": now,
                "source": "farmer_voice_confirmed",
            }
            client.table("farms").update({"irrigation_availability": payload, "updated_at": now}).eq("id", real_farm_id).execute()

        elif target_field == "labour_availability":
            payload = {
                "value": raw_val,
                "evidence_label": evidence,
                "confirmed_at": now,
                "source": "farmer_voice_confirmed",
            }
            client.table("farms").update({"labour_availability": payload, "updated_at": now}).eq("id", real_farm_id).execute()

        elif target_field.startswith("soil."):
            attr = target_field.split(".")[1]
            soil_dict = farm.soil.model_dump(mode="json")
            soil_dict[attr] = {
                "value": raw_val,
                "evidence_label": evidence,
                "confirmed_at": now,
                "source": "farmer_voice_confirmed",
            }
            client.table("farms").update({"soil": soil_dict, "updated_at": now}).eq("id", real_farm_id).execute()

        elif target_field == "priorities":
            priorities_dict = farm.priorities.model_dump(mode="json")
            key = str(value)
            if key in priorities_dict:
                priorities_dict[key] = 3
            client.table("farms").update({"priorities": priorities_dict, "updated_at": now}).eq("id", real_farm_id).execute()

        elif target_field == "crop_history":
            crop_id = value.get("crop_id") if isinstance(value, dict) else None
            raw_name = value.get("raw_crop_name", str(value)) if isinstance(value, dict) else str(value)
            client.table("crop_history").insert(
                {
                    "farm_id": real_farm_id,
                    "user_id": user_id,
                    "season": "previous_season",
                    "crop_id": crop_id,
                    "raw_crop_name": raw_name,
                    "evidence_label": evidence,
                    "confirmed_at": now,
                }
            ).execute()

        elif target_field == "field_observations":
            obs_row: dict[str, Any] = {
                "farm_id": real_farm_id,
                "user_id": user_id,
                "evidence_label": evidence,
                "source": "farmer-confirmed",
                "recorded_at": now,
            }
            if isinstance(value, dict):
                obs_row.update(
                    {
                        "zone": value.get("zone") or "general",
                        "event_type": value.get("event_type") or "general",
                        "affected_crop": value.get("affected_crop"),
                        "timing_or_duration": value.get("timing_or_duration"),
                        "observation": value.get("observation") or str(value),
                    }
                )
            else:
                obs_row["observation"] = str(value)
            client.table("field_observations").insert(obs_row).execute()

        return self.get_or_create_farm(real_farm_id, user_id=user_id, access_token=access_token)
