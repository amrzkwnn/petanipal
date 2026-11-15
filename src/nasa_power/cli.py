"""Command-line interface for fetching regional NASA POWER data."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from .client import (
    COMMUNITIES,
    OUTPUT_FORMATS,
    TEMPORAL_SCALES,
    NasaPowerRegionalClient,
)
from .presets import PRESETS, BoundingBox


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nasa-power",
        description="Fetch regional meteorological and solar data from the NASA POWER API.",
    )
    parser.add_argument(
        "--preset",
        choices=sorted(PRESETS.keys()),
        help="Named regional bounding-box preset (e.g., indonesia_java_sea).",
    )
    parser.add_argument("--lat-min", type=float, help="Minimum latitude (-90 to 90).")
    parser.add_argument("--lat-max", type=float, help="Maximum latitude (-90 to 90).")
    parser.add_argument("--lon-min", type=float, help="Minimum longitude (-180 to 180).")
    parser.add_argument("--lon-max", type=float, help="Maximum longitude (-180 to 180).")
    parser.add_argument(
        "--temporal",
        default="daily",
        choices=TEMPORAL_SCALES,
        help="Temporal resolution (default: daily).",
    )
    parser.add_argument(
        "--community",
        default="RE",
        choices=COMMUNITIES,
        help="NASA POWER community: RE, AG, or SB (default: RE).",
    )
    parser.add_argument(
        "--parameters",
        required=True,
        help="Comma-separated NASA POWER parameter codes (max 20), e.g. T2M,PRECTOTCORR.",
    )
    parser.add_argument("--start", help="Start date (YYYYMMDD for daily/hourly, YYYY for monthly).")
    parser.add_argument("--end", help="End date (YYYYMMDD for daily/hourly, YYYY for monthly).")
    parser.add_argument(
        "--format",
        dest="output_format",
        default="CSV",
        choices=OUTPUT_FORMATS,
        help="Output format (default: CSV).",
    )
    parser.add_argument(
        "--tidy",
        action="store_true",
        help="Fetch JSON and flatten into a tidy tabular CSV (latitude, longitude, date, params).",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output file path (e.g., data/indonesia_daily.csv).",
    )
    return parser


def _resolve_bbox(args: argparse.Namespace) -> BoundingBox:
    if args.preset:
        return PRESETS[args.preset]

    coords = (args.lat_min, args.lat_max, args.lon_min, args.lon_max)
    if any(c is None for c in coords):
        raise ValueError(
            "Provide either --preset or all four --lat-min, --lat-max, --lon-min, --lon-max."
        )
    return BoundingBox(
        lat_min=args.lat_min,
        lat_max=args.lat_max,
        lon_min=args.lon_min,
        lon_max=args.lon_max,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    bbox = _resolve_bbox(args)
    client = NasaPowerRegionalClient()
    output_path = Path(args.output)

    if args.tidy:
        df = client.fetch_dataframe(
            bbox=bbox,
            parameters=args.parameters,
            temporal=args.temporal,
            community=args.community,
            start=args.start,
            end=args.end,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_path, index=False)
        print(f"Saved {len(df)} rows to {output_path}")
        return 0

    saved = client.download(
        output_path=output_path,
        bbox=bbox,
        parameters=args.parameters,
        temporal=args.temporal,
        community=args.community,
        start=args.start,
        end=args.end,
        output_format=args.output_format,
    )
    print(f"Saved regional {args.output_format} data to {saved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
