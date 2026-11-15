"""Regional bounding-box presets and coordinate types."""

from dataclasses import dataclass


@dataclass(frozen=True)
class BoundingBox:
    """Geographic bounding box in decimal degrees."""

    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float

    def __post_init__(self) -> None:
        if not (-90.0 <= self.lat_min < self.lat_max <= 90.0):
            raise ValueError(
                f"Invalid latitude bounds ({self.lat_min}, {self.lat_max}): "
                "expected -90 <= lat_min < lat_max <= 90."
            )
        if not (-180.0 <= self.lon_min < self.lon_max <= 180.0):
            raise ValueError(
                f"Invalid longitude bounds ({self.lon_min}, {self.lon_max}): "
                "expected -180 <= lon_min < lon_max <= 180."
            )


PRESETS: dict[str, BoundingBox] = {
    # Centered near lat=-5.207, lon=108.241 from link.md (2° x 2° bounding box)
    "indonesia_java_sea": BoundingBox(
        lat_min=-6.2,
        lat_max=-4.2,
        lon_min=107.2,
        lon_max=109.2,
    ),
    # Kedah, Malaysia & Langkawi (2°+ range required by NASA POWER regional API)
    "kedah": BoundingBox(
        lat_min=4.8,
        lat_max=6.8,
        lon_min=99.3,
        lon_max=101.4,
    ),
}
