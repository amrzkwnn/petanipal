from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class WaterNeed(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    MEDIUM_HIGH = "medium_high"
    HIGH = "high"


class ToleranceLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class NitrogenEffect(str, Enum):
    NITROGEN_FIXING = "nitrogen_fixing"
    LOW_DEMAND = "low_demand"
    MEDIUM_DEMAND = "medium_demand"
    HIGH_DEMAND = "high_demand"


class DurationDays(BaseModel):
    min: int = Field(..., ge=1)
    max: int = Field(..., ge=1)


class PHRange(BaseModel):
    min: Optional[float] = Field(None, ge=0.0, le=14.0)
    max: Optional[float] = Field(None, ge=0.0, le=14.0)


class CropProfile(BaseModel):
    """Reviewed agronomic profile for a locally relevant crop."""

    crop_id: str
    names: dict[str, list[str]] = Field(
        ..., description="Spoken/display names keyed by language code ('en', 'ms')."
    )
    production_system: str = "open_field"
    cycle_type: str = Field(
        ..., description="'seasonal' (2-4 months) or 'multi_season' (9+ months)."
    )
    family: str
    duration_days: DurationDays
    water_need: WaterNeed
    flood_tolerance: ToleranceLevel
    heat_tolerance: ToleranceLevel
    soil_preferences: list[str]
    ph_range: PHRange
    nitrogen_effect: NitrogenEffect
    ground_cover: ToleranceLevel
    rotation_warnings: list[str]
    geotanih_crop_id: Optional[int] = None
    geotanih_crop_name: Optional[str] = None
    source_name: str
    source_url: str
    last_reviewed: date
    review_status: str = "draft_needs_local_review"

    @property
    def id(self) -> str:
        return self.crop_id


class CropLibrary(BaseModel):
    locality: str
    last_updated: date
    crops: list[CropProfile]
