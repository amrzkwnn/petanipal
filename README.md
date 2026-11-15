# NASA POWER Regional API Client

Python client and CLI for pulling regional (bounding-box) meteorological and solar data from the [NASA POWER API](https://power.larc.nasa.gov/).

## Setup

Uses `uv` with Python 3.12+:

```powershell
uv sync --extra dev
```

## CLI Usage

> Note: On Windows systems with Application Control policies blocking `.venv/Scripts/*.exe`, invoke the CLI via `uv run python -m nasa_power.cli`.

Download raw CSV (1 parameter per raw regional request) using the `indonesia_java_sea` preset (centered near `lat=-5.207, lon=108.241` from `link.md`):

```powershell
uv run python -m nasa_power.cli `
  --preset indonesia_java_sea `
  --parameters T2M `
  --start 20250101 `
  --end 20250107 `
  --format CSV `
  --output data/indonesia_daily.csv
```

Or fetch multiple parameters and flatten them into a tidy tabular CSV (`latitude, longitude, date, ...`):

```powershell
uv run python -m nasa_power.cli `
  --preset indonesia_java_sea `
  --parameters T2M,PRECTOTCORR `
  --start 20250101 `
  --end 20250107 `
  --tidy `
  --output data/indonesia_tidy.csv
```

Custom bounding box:

```powershell
uv run python -m nasa_power.cli `
  --lat-min -6.5 --lat-max -4.5 `
  --lon-min 107.0 --lon-max 109.0 `
  --temporal monthly `
  --community AG `
  --parameters T2M `
  --start 2024 --end 2024 `
  --format JSON `
  --output data/monthly.json
```

## Python Usage

```python
from nasa_power import NasaPowerRegionalClient, PRESETS

client = NasaPowerRegionalClient()
df = client.fetch_dataframe(
    bbox=PRESETS["indonesia_java_sea"],
    parameters=["T2M", "PRECTOTCORR"],
    temporal="daily",
    community="RE",
    start="20250101",
    end="20250105",
)
print(df.head())
```

## Notes
- NASA POWER Regional endpoints currently allow **1 parameter per raw request** (`download()` / `fetch_raw()`). Use `fetch_dataframe()` or `--tidy` to fetch and merge multiple parameters automatically.
- Keep regional bounding boxes reasonably sized to avoid NASA POWER server timeouts.
- Missing values (`-999`) are automatically converted to `NaN` in `fetch_dataframe()`.

## Tests

```powershell
uv run pytest -v
```
