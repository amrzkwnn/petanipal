from datetime import datetime
from enum import Enum
from typing import Generic, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class LanguageCode(str, Enum):
    EN = "en"
    MS = "ms"


class EvidenceLabel(str, Enum):
    VERIFIED_BY_FARMER = "verified_by_farmer"
    ESTIMATED_FROM_MAP = "estimated_from_map"
    ESTIMATED_FROM_CLIMATE = "estimated_from_climate"
    HISTORICAL_TREND = "historical_trend"
    UNKNOWN = "unknown"


class TrackedValue(BaseModel, Generic[T]):
    """A farm attribute paired with its provenance and confirmation timestamp."""

    value: Optional[T] = None
    evidence_label: EvidenceLabel = EvidenceLabel.UNKNOWN
    confirmed_at: Optional[datetime] = None
    source: Optional[str] = None


class IrrigationAvailability(str, Enum):
    ALWAYS = "always"
    SOMETIMES = "sometimes"
    NO = "no"
    UNKNOWN = "unknown"


class WaterloggingDuration(str, Enum):
    SAME_DAY = "same_day"
    ONE_TO_TWO_DAYS = "1_to_2_days"
    OVER_TWO_DAYS = "over_2_days"
    UNKNOWN = "unknown"


class SoilFeel(str, Enum):
    STICKY = "sticky"
    SANDY = "sandy"
    IN_BETWEEN = "in_between"
    UNKNOWN = "unknown"


class SoilTestStatus(str, Enum):
    YES_KNOWN = "yes_known"
    YES_UNKNOWN_RESULT = "yes_unknown_result"
    NO_TEST = "no_test"
    UNKNOWN = "unknown"


class FarmLocation(BaseModel):
    locality: str = "Sungai Petani, Kedah"
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class SoilContext(BaseModel):
    texture_feel: TrackedValue[SoilFeel] = Field(
        default_factory=lambda: TrackedValue(value=SoilFeel.UNKNOWN)
    )
    waterlogging_duration: TrackedValue[WaterloggingDuration] = Field(
        default_factory=lambda: TrackedValue(value=WaterloggingDuration.UNKNOWN)
    )
    flooded_last_season: TrackedValue[str] = Field(
        default_factory=lambda: TrackedValue(value="unknown")
    )
    ph: TrackedValue[float] = Field(default_factory=lambda: TrackedValue(value=None))
    soil_test_status: TrackedValue[SoilTestStatus] = Field(
        default_factory=lambda: TrackedValue(value=SoilTestStatus.UNKNOWN)
    )
    trouble_spot: TrackedValue[str] = Field(
        default_factory=lambda: TrackedValue(value="unknown")
    )


class CropHistoryEntry(BaseModel):
    season: str
    crop_id: Optional[str] = None
    raw_crop_name: str
    issue: Optional[str] = None
    evidence_label: EvidenceLabel = EvidenceLabel.VERIFIED_BY_FARMER
    confirmed_at: Optional[datetime] = None


class FieldObservation(BaseModel):
    zone: str = "general"
    event_type: str = "general"
    affected_crop: Optional[str] = None
    timing_or_duration: Optional[str] = None
    observation: str
    evidence_label: EvidenceLabel = EvidenceLabel.VERIFIED_BY_FARMER
    source: str = "farmer-confirmed"
    recorded_at: datetime


class Priorities(BaseModel):
    water: int = Field(0, ge=0, le=3)
    soil_health: int = Field(0, ge=0, le=3)
    income: int = Field(0, ge=0, le=3)
    risk_reduction: int = Field(0, ge=0, le=3)


class FarmMemory(BaseModel):
    """Structured, farmer-confirmed farm profile (never stores raw voice audio)."""

    farm_id: str
    preferred_language: LanguageCode = LanguageCode.MS
    location: FarmLocation = Field(default_factory=FarmLocation)
    irrigation_availability: TrackedValue[IrrigationAvailability] = Field(
        default_factory=lambda: TrackedValue(value=IrrigationAvailability.UNKNOWN)
    )
    labour_availability: TrackedValue[str] = Field(
        default_factory=lambda: TrackedValue(value="unknown")
    )
    soil: SoilContext = Field(default_factory=SoilContext)
    crop_history: list[CropHistoryEntry] = Field(default_factory=list)
    field_observations: list[FieldObservation] = Field(default_factory=list)
    priorities: Priorities = Field(default_factory=Priorities)
