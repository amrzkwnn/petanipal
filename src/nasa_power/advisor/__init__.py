"""Farm Memory crop-rotation decision support advisor package."""

from .context_data import load_geotanih_context, load_market_context
from .conversation import classify_farmer_message, handle_farmer_chat
from .data_fetcher import DailyClimateSummary, NasaPowerDailyFetcher
from .engine import RotationComparison, compare_rotations, load_crop_catalog
from .farm_memory import QUESTION_LIBRARY, FarmMemoryRecord, FarmMemoryStore, next_useful_question

__all__ = [
    "DailyClimateSummary",
    "FarmMemoryRecord",
    "FarmMemoryStore",
    "NasaPowerDailyFetcher",
    "QUESTION_LIBRARY",
    "RotationComparison",
    "classify_farmer_message",
    "compare_rotations",
    "handle_farmer_chat",
    "load_crop_catalog",
    "load_geotanih_context",
    "load_market_context",
    "next_useful_question",
]
