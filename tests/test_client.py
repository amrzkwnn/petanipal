"""Unit tests for the NASA POWER Regional API client and CLI."""

from __future__ import annotations

import json
import math
from unittest.mock import MagicMock

import pytest

from nasa_power import PRESETS, BoundingBox, NasaPowerApiError, NasaPowerRegionalClient
from nasa_power.cli import main
from nasa_power.client import parse_regional_json_to_dataframe


def test_bounding_box_validation() -> None:
    with pytest.raises(ValueError, match="latitude"):
        BoundingBox(lat_min=10.0, lat_max=5.0, lon_min=100.0, lon_max=105.0)

    with pytest.raises(ValueError, match="longitude"):
        BoundingBox(lat_min=-5.0, lat_max=5.0, lon_min=190.0, lon_max=195.0)


def test_build_url_and_params() -> None:
    client = NasaPowerRegionalClient()
    bbox = PRESETS["indonesia_java_sea"]

    assert client.build_url("daily") == "https://power.larc.nasa.gov/api/temporal/daily/regional"
    assert client.build_url("monthly") == "https://power.larc.nasa.gov/api/temporal/monthly/regional"

    params = client.build_params(
        bbox=bbox,
        parameters=["T2M"],
        temporal="daily",
        community="ag",
        start="20250101",
        end="20250102",
        output_format="csv",
    )
    assert params == {
        "parameters": "T2M",
        "community": "AG",
        "latitude-min": -6.2,
        "latitude-max": -4.2,
        "longitude-min": 107.2,
        "longitude-max": 109.2,
        "format": "CSV",
        "start": "20250101",
        "end": "20250102",
    }


def test_parameter_limit_and_missing_dates() -> None:
    client = NasaPowerRegionalClient()
    bbox = PRESETS["indonesia_java_sea"]

    with pytest.raises(ValueError, match="at most 1 parameter"):
        client.build_params(
            bbox=bbox,
            parameters=["T2M", "PRECTOTCORR"],
            start="20250101",
            end="20250102",
        )

    with pytest.raises(ValueError, match="start"):
        client.build_params(bbox=bbox, parameters="T2M", temporal="daily")

    # Climatology does not require start/end
    clim = client.build_params(bbox=bbox, parameters="T2M", temporal="climatology")
    assert "start" not in clim


def test_parse_feature_collection_to_dataframe() -> None:
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [108.0, -5.0]},
                "properties": {
                    "parameter": {
                        "T2M": {"20250101": 27.5, "20250102": -999},
                        "PRECTOTCORR": {"20250101": 3.2, "20250102": 0.0},
                    }
                },
            }
        ],
    }

    df = parse_regional_json_to_dataframe(payload)
    assert list(df.columns) == ["latitude", "longitude", "date", "T2M", "PRECTOTCORR"]
    assert len(df) == 2
    assert df.loc[0, "latitude"] == -5.0
    assert df.loc[0, "longitude"] == 108.0
    assert df.loc[0, "T2M"] == 27.5
    assert math.isnan(df.loc[1, "T2M"])


def test_fetch_and_download_mocked(tmp_path) -> None:
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b"LAT,LON,YEAR,DOY,T2M\n-5.0,108.0,2025,1,27.5\n"
    mock_session.get.return_value = mock_response

    client = NasaPowerRegionalClient(session=mock_session)
    out = tmp_path / "out.csv"
    saved = client.download(
        output_path=out,
        bbox=PRESETS["indonesia_java_sea"],
        parameters="T2M",
        start="20250101",
        end="20250101",
        output_format="CSV",
    )

    assert saved == out
    assert out.read_text(encoding="utf-8").startswith("LAT,LON")


def test_api_error_raises() -> None:
    mock_session = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 422
    mock_response.text = "Unprocessable Entity"
    mock_session.get.return_value = mock_response

    client = NasaPowerRegionalClient(session=mock_session)
    with pytest.raises(NasaPowerApiError, match="422"):
        client.fetch_raw(
            bbox=PRESETS["indonesia_java_sea"],
            parameters="T2M",
            start="20250101",
            end="20250101",
        )


def test_cli_tidy_csv(monkeypatch, tmp_path) -> None:
    def fake_fetch_raw(self, **kwargs):
        param = kwargs["parameters"]
        val = 28.1 if param == "T2M" else 4.5
        return {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[107.2, -6.2], [109.2, -6.2], [109.2, -4.2], [107.2, -4.2], [107.2, -6.2]]],
            },
            "properties": {"parameter": {param: {"20250101": val}}},
        }

    monkeypatch.setattr(NasaPowerRegionalClient, "fetch_raw", fake_fetch_raw)
    out = tmp_path / "tidy.csv"
    rc = main(
        [
            "--preset",
            "indonesia_java_sea",
            "--parameters",
            "T2M,PRECTOTCORR",
            "--start",
            "20250101",
            "--end",
            "20250101",
            "--tidy",
            "--output",
            str(out),
        ]
    )
    assert rc == 0
    text = out.read_text(encoding="utf-8")
    assert "T2M,PRECTOTCORR" in text
    assert "28.1,4.5" in text
