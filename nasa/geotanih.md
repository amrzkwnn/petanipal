# GeoTanih integration guide

## Purpose

This document tells the coding agent how to use Malaysia Department of Agriculture (DOA) GeoTanih in **Farm Memory**, a crop-rotation decision-support prototype.

GeoTanih is useful as a **mapped soil-suitability context layer**. It is **not** a replacement for a current soil test, a field inspection, or farmer-confirmed knowledge.

Use it to say:

> “The mapped soil context indicates a possible drainage limitation. Please confirm whether water remains after heavy rain.”

Do not use it to say:

> “This field has pH 5.4.”

> “This field is definitely suitable for chilli.”

> “Plant this crop.”

## Scope and important limitations

- GeoTanih is primarily a soil-information system for **Peninsular Malaysia**. Treat Sabah and Sarawak as unsupported unless a different verified local source is added.
- A map result describes a mapped soil polygon or mapping unit, not an exact laboratory reading from every part of a field.
- A field may cross more than one soil polygon. A single centre-point query is only a prototype shortcut.
- GeoTanih currently exposes useful public endpoints, but there is no developer-focused, documented, versioned API contract or published reuse/rate-limit guarantee found during research.
- The live endpoints can change, require a token, be rate-limited, or be removed. Call them only from the backend and cache results.
- For a deployed product, request written permission, a supported data feed, and reuse terms from DOA/GeoTanih.

## What the live map can actually return

The current official GeoTanih map configuration points to this ArcGIS service:

```text
https://geotanaman.doa.gov.my/mygeosvr/rest/services/SM_SCSC_3/MapServer
```

Use layer `0` for point or polygon queries:

```text
https://geotanaman.doa.gov.my/mygeosvr/rest/services/SM_SCSC_3/MapServer/0
```

The layer is a polygon feature layer with public `Map`, `Query`, and `Data` capabilities. It supports JSON and GeoJSON output.

At the time of verification, the location-specific attribute schema contains only:

| Field | Meaning to the app | Safe interpretation |
|---|---|---|
| `SF_teren` | Mapping-unit / terrain label | Keep as a source identifier; do not show raw code to a farmer. |
| `S_Family` | Soil family | Mapped soil-family context, not a current soil-test result. |
| `Class_1` | Compact suitability/limitation code, for example `4cdst` | An opaque map classification. It may signal broad limitations, but is not an exact list of measured values. |
| Geometry | Soil polygon boundary | Can be used to identify whether the selected field overlaps more than one mapping unit. |

The layer **does not directly return** a `pH`, N-P-K value, organic-carbon percentage, measured soil moisture, exact drainage-class field, or a crop-rotation recommendation.

## Public supporting endpoints

The GeoTanih public map itself uses the following reference endpoints. They are useful for a controlled prototype, but are not guaranteed public-product APIs.

| Endpoint | Use | Important limitation |
|---|---|---|
| `https://geotanih.doa.gov.my/api/admin/setting?module=SuitabilityMap` | Reads the current official map-service configuration. | Do not assume the returned service URL will stay unchanged. |
| `https://geotanih.doa.gov.my/api/suitability` | Lists soil-suitability limitation categories. | A category catalogue, not a location-specific measurement. |
| `https://geotanih.doa.gov.my/api/suitability/soilCriteria` | Lists reference criteria and symbols, such as drainage, slope, salinity, texture, and compacted-layer conditions. | It describes possible criteria. Do not claim every value applies to a selected field. |
| `https://geotanih.doa.gov.my/api/suitability/cropCriteria?inMalay=true` | Crop-to-soil-criteria reference records. | Crop coverage is limited; the service is not a complete crop library. |
| `https://geotanih.doa.gov.my/api/suitability/management?page=0` | General management text associated with suitability symbols. | General advice, not a site-specific prescription. |

The public GeoTanih map combines the location's `Class_1` code with these reference records to display a suitability class, crop groups, and management context.

### Crop-coverage gap

The public crop-criteria endpoint currently contains 63 named crops. It includes examples such as:

- `Jagung` (maize)
- `Kacang Tanah` (groundnut)
- `Keledek` (sweet potato)
- `Padi Sawah` (rice)
- `Nanas` (pineapple)
- `Pisang` (banana)
- `Sayur - Sayuran` (a generic vegetables category)

It does **not** currently contain specific `Cili`/chilli or `Tomato` records. Therefore:

- Do not use GeoTanih as the sole crop-suitability source for chilli, tomato, or any crop absent from its current catalogue.
- Maintain Farm Memory's own reviewed crop library, based on DOA/MARDI and locally checked sources.
- For an unsupported crop, use GeoTanih only to flag broad mapped land limitations such as possible drainage, slope, salinity, or texture concerns.

## Recommended role in the decision engine

```text
GeoTanih
  = mapped soil suitability and possible limitation context

NASA POWER
  = historical climate and weather-stress context

Farm Memory
  = field history, irrigation, observed flooding, pests, priorities,
    farmer-confirmed conditions, and outcomes

Reviewed crop library
  = crop duration, crop family, water need, heat/flood tolerance,
    soil preference, nitrogen contribution, and rotation constraints

Rotation engine
  = explainable comparison of options; never an instruction to plant
```

The rotation engine should give GeoTanih an evidence label of:

```text
Estimated from soil map
```

It should upgrade confidence only when map context agrees with a farmer-confirmed observation or a recent soil test.

## Two safe ways to use GeoTanih

### Option A — fastest hackathon prototype: manually verified locality record

Use this when a stable data integration is not yet approved.

1. Pick the single prototype locality in Peninsular Malaysia.
2. Open the [GeoTanih Soil-Crop Suitability Map](https://geotanih.doa.gov.my/suitability/map).
3. Enter the locality/farm latitude and longitude, or place the pin.
4. Record the displayed suitability class, crop groups, and management notes.
5. Save a small, dated record in the project database/configuration.
6. Show the date and source in the app.

Example seed record:

```json
{
  "source": "GeoTanih, Department of Agriculture Malaysia",
  "source_url": "https://geotanih.doa.gov.my/suitability/map",
  "retrieved_at": "2026-11-14",
  "locality": "chosen prototype locality",
  "evidence_label": "Estimated from soil map",
  "notes": "Mapped soil context; not a field soil test"
}
```

Do not scrape the interactive web page. This option is a manually checked prototype reference, not a live data pipeline.

### Option B — backend GIS adapter: controlled technical demo

Use this only after validating it against the public map at several known points and after checking current DOA terms.

1. The farmer selects a field point or draws a field boundary.
2. The client sends coordinates to **our backend**, never directly to GeoTanih.
3. The backend queries the official ArcGIS layer.
4. The backend normalises the returned map context, caches it, and stores the retrieval date and source URL.
5. The rotation engine uses the context as an estimate, then asks the farmer for confirmation of decision-critical conditions.

### Point-query pattern

```text
GET https://geotanaman.doa.gov.my/mygeosvr/rest/services/SM_SCSC_3/MapServer/0/query
  ?f=json
  &where=1%3D1
  &geometry={longitude}%2C{latitude}
  &geometryType=esriGeometryPoint
  &inSR=4326
  &spatialRel=esriSpatialRelIntersects
  &outFields=SF_teren%2CS_Family%2CClass_1
  &returnGeometry=false
```

Expected response shape:

```json
{
  "features": [
    {
      "attributes": {
        "SF_teren": "source mapping label",
        "S_Family": "source soil family",
        "Class_1": "source class code"
      }
    }
  ]
}
```

### Required backend behaviour

```text
validate latitude/longitude
        ↓
query the MapServer layer with a short timeout
        ↓
no feature returned? → status = no_map_coverage; do not guess
        ↓
feature returned? → save mapped soil context with evidence label
        ↓
cache result by field/location and refresh only intentionally
        ↓
if service fails → use last dated cache, or say soil-map context is unavailable
```

Recommended normalised record:

```json
{
  "provider": "Department of Agriculture Malaysia — GeoTanih",
  "status": "available",
  "retrieved_at": "ISO-8601 timestamp",
  "source_url": "https://geotanaman.doa.gov.my/mygeosvr/rest/services/SM_SCSC_3/MapServer/0",
  "query_type": "field-centre point",
  "latitude": 0,
  "longitude": 0,
  "mapping_unit": "SF_teren value",
  "soil_family": "S_Family value",
  "suitability_code": "Class_1 value",
  "evidence_label": "Estimated from soil map",
  "limitations": [],
  "management_context": [],
  "raw_response_version": "optional, internal only"
}
```

## Do not over-decode `Class_1`

`Class_1` is a compact source code. It can look like `4cdst`, where letters may correspond to limitation symbols used in the GeoTanih reference catalogues.

Rules for the coding agent:

- Do not show the raw code to farmers.
- Do not convert one code into an exact pH, nutrient concentration, soil-moisture value, or drainage duration.
- Do not infer a precise drainage class unless it is returned by an authorised, documented source or confirmed by the farmer/test.
- Do not independently reimplement GeoTanih's crop-suitability algorithm unless its output has been validated against the official map for several locations and reviewed by an agricultural expert.
- Until then, use the code only as map context and a trigger for plain-language confirmation questions.

Safe example:

> “The soil map suggests there may be a water-management limitation here. After heavy rain, does water stay on the field for more than two days?”

Unsafe example:

> “Your field is poorly drained.”

## Field boundaries and multiple soil polygons

For the first prototype, a field-centre point is acceptable if the app labels it clearly.

For a later version:

1. Send the field polygon to the backend.
2. Query intersecting map polygons.
3. Calculate the percentage of the field occupied by each mapping unit.
4. Return the dominant unit and flag mixed soil context when more than one material polygon is present.
5. Never silently reduce a mixed field to one "true" soil type.

Suggested farmer-facing wording:

> “This field crosses more than one mapped soil area. The app is using the dominant mapped area, so please confirm conditions in the lower and upper parts of the field.”

## How GeoTanih should affect the voice interview

GeoTanih should make the app ask better questions, not pretend to know all answers.

| Map context or uncertainty | Farmer-friendly follow-up |
|---|---|
| Possible drainage/water limitation | “After heavy rain, how long does water stay on this field?” |
| Possible slope/erosion concern | “Does soil wash away or form channels when rain is heavy?” |
| Possible texture/structure concern | “When the soil is wet, does it feel sticky, sandy, or in-between?” |
| Crop not covered by GeoTanih | “We have soil-map context, but this crop needs a separate reviewed crop profile.” |
| No map result | “I could not find soil-map data for this location. Do you know whether water stays after rain, or do you have a soil-test result?” |

Store the answer only after the farmer confirms it. Do not store raw voice recordings.

## Data that must come from elsewhere

| Need | Primary source for Farm Memory |
|---|---|
| Historical rainfall, heat, dry spells, humidity | NASA POWER |
| Exact pH, N-P-K, organic matter, EC/salinity, soil-test values | Recent soil test or agricultural officer/lab report |
| Actual waterlogging duration, irrigation access, pest history | Farmer-confirmed Farm Memory |
| Crop family, crop duration, water need, heat/flood tolerance, rotation effect | Reviewed crop library (DOA/MARDI and locally checked sources) |
| Market and buyer context | Authorised FAMA or other official market source |

## Validation checklist before demo

- [ ] Prototype locality is in Peninsular Malaysia.
- [ ] Test at least three real coordinates in the chosen locality using the official GeoTanih map.
- [ ] For each coordinate, compare the app's map response with the GeoTanih map's displayed suitability result.
- [ ] Verify that every prototype crop is either explicitly represented in GeoTanih or covered by the project's own reviewed crop library.
- [ ] For unsupported crops such as chilli, ensure the UI does not claim “GeoTanih says this crop is suitable.”
- [ ] Test `no feature`, network failure, timeout, and malformed-coordinate states.
- [ ] Display source, retrieval date, evidence label, and data gap in every farmer-facing result.
- [ ] Cache reads and do not query GeoTanih on every voice message or every screen refresh.
- [ ] Confirm the current terms of use and obtain permission before public deployment or large-scale automated use.

## Source links

- [GeoTanih public site](https://geotanih.doa.gov.my/)
- [GeoTanih soil-crop suitability map](https://geotanih.doa.gov.my/suitability/map)
- [GeoTanih user manual](https://geotanih.doa.gov.my/pdf/user_manual.pdf)
- [Live suitability-map configuration](https://geotanih.doa.gov.my/api/admin/setting?module=SuitabilityMap)
- [Live ArcGIS layer metadata](https://geotanaman.doa.gov.my/mygeosvr/rest/services/SM_SCSC_3/MapServer/0?f=pjson)
- [GeoTanih terms of use](https://geotanih.doa.gov.my/termuse)

## Final implementation decision

Use GeoTanih in the prototype, but only as **dated, mapped soil-suitability context**. It is valuable because it makes the app locally Malaysian and helps trigger the right farmer questions. It must be combined with NASA POWER, Farm Memory, a reviewed crop library, and—where available—a recent soil test.
