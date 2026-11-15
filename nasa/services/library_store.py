import json
from pathlib import Path
from typing import Optional

from schemas import CropLibrary, CropProfile, FarmMemory, LanguageCode, QuestionItem, QuestionLibrary, ToleranceLevel


class LibraryStore:
    """Loads reviewed crop and question libraries from disk."""

    def __init__(self, data_dir: Path | str | None = None) -> None:
        self.data_dir = Path(data_dir) if data_dir is not None else (Path(__file__).resolve().parents[1] / "data")
        self.crop_library = self._load_crops()
        self.question_library = self._load_questions()
        self._crops_by_id = {c.crop_id: c for c in self.crop_library.crops}
        self._questions_by_id = {q.question_id: q for q in self.question_library.questions}

    def _load_crops(self) -> CropLibrary:
        raw = json.loads((self.data_dir / "crops.json").read_text(encoding="utf-8"))
        return CropLibrary.model_validate(raw)

    def _load_questions(self) -> QuestionLibrary:
        raw = json.loads((self.data_dir / "question_library.json").read_text(encoding="utf-8"))
        return QuestionLibrary.model_validate(raw)

    def list_crops(self) -> list[CropProfile]:
        return self.crop_library.crops

    def get_crop(self, crop_id: str) -> Optional[CropProfile]:
        return self._crops_by_id.get(crop_id)

    def match_crop_name(self, spoken_name: str) -> Optional[CropProfile]:
        """Normalise a spoken English or Bahasa Malaysia crop name to a verified CropProfile."""
        needle = spoken_name.strip().lower()
        if not needle:
            return None
        for crop in self.crop_library.crops:
            if crop.crop_id == needle:
                return crop
            for lang_names in crop.names.values():
                if any(name.lower() == needle for name in lang_names):
                    return crop
        return None

    def list_questions(self) -> list[QuestionItem]:
        return sorted(self.question_library.questions, key=lambda q: q.priority)

    _QUESTION_ALIASES = {
        "q01_last_crop": "crop_history",
        "q02_waterlogging": "waterlogging_duration",
        "q03_irrigation": "irrigation_availability",
        "q04_soil_feel": "soil_feel",
        "q05_flood_history": "flood_last_season",
        "q06_priority": "farmer_priority",
        "q07_soil_test": "soil_test",
        "q08_previous_crop_issue": "field_problems",
        "q09_trouble_spot": "trouble_spot",
        "q10_labour": "labour_availability",
    }

    def get_question(self, question_id: str) -> Optional[QuestionItem]:
        resolved = self._QUESTION_ALIASES.get(question_id, question_id)
        return self._questions_by_id.get(resolved)

    def get_next_question(
        self,
        farm: FarmMemory,
        geotanih_flags: Optional[set[str]] = None,
    ) -> Optional[QuestionItem]:
        """Return the highest-priority unanswered question applicable to this farm."""
        flags = set(geotanih_flags or ())
        if farm.soil.flooded_last_season.value == "yes":
            flags.add("farmer_reported_flooding")
        if farm.crop_history:
            last_crop_id = farm.crop_history[-1].crop_id
            last_crop = self.get_crop(last_crop_id) if last_crop_id else None
            if last_crop and last_crop.flood_tolerance == ToleranceLevel.LOW:
                flags.add("crop_flood_sensitive")

        for q in self.list_questions():
            if self._is_answered(farm, q.target_field):
                continue
            if "always_essential" in q.ask_when or "helpful_context" in q.ask_when:
                return q
            if any(trigger in flags for trigger in q.ask_when):
                return q
        return None

    def get_optional_checkin(
        self,
        farm: FarmMemory,
        language: LanguageCode = LanguageCode.MS,
    ) -> Optional[dict[str, str]]:
        """Return at most one gentle, optional check-in prompt based on saved FarmMemory."""
        for obs in reversed(farm.field_observations):
            if obs.event_type == "pest":
                return {
                    "checkin_type": "pest_followup",
                    "prompt": (
                        f"Sebelum ni anda ada bagitahu masalah serangga ({obs.observation}). Sekarang masih ada lagi ke?"
                        if language == LanguageCode.MS
                        else f"Earlier you mentioned a pest issue ({obs.observation}). Is that still happening?"
                    ),
                }
            if obs.event_type in ("flooding", "waterlogging"):
                return {
                    "checkin_type": "drainage_followup",
                    "prompt": (
                        "Lepas hujan baru-baru ni, air ada bertakung lagi tak kat kebun?"
                        if language == LanguageCode.MS
                        else "After the recent rain, did water stay on the field?"
                    ),
                }
            if obs.event_type == "equipment":
                return {
                    "checkin_type": "equipment_followup",
                    "prompt": (
                        f"Hari tu ada sebut pasal peralatan ({obs.observation}). Sekarang dah okay ke?"
                        if language == LanguageCode.MS
                        else f"Earlier you mentioned an equipment issue ({obs.observation}). Is it working again now?"
                    ),
                }

        next_q = self.get_next_question(farm)
        if next_q:
            return {
                "checkin_type": "next_useful_question",
                "question_id": next_q.question_id,
                "prompt": next_q.prompts.get(language.value, next_q.prompts["en"]),
            }
        return None

    @staticmethod
    def _is_answered(farm: FarmMemory, target_field: str) -> bool:
        if target_field == "crop_history":
            return len(farm.crop_history) > 0
        if target_field == "field_observations":
            return len(farm.field_observations) > 0
        if target_field == "priorities":
            p = farm.priorities
            return any(v > 0 for v in (p.water, p.soil_health, p.income, p.risk_reduction))

        parts = target_field.split(".")
        obj: object = farm
        for part in parts:
            obj = getattr(obj, part, None)
            if obj is None:
                return False
        # TrackedValue has .evidence_label, .value, and .confirmed_at
        if getattr(obj, "confirmed_at", None) is not None:
            return True
        evidence = getattr(obj, "evidence_label", None)
        value = getattr(obj, "value", None)
        return evidence is not None and evidence.value != "unknown" and value not in (None, "unknown")
