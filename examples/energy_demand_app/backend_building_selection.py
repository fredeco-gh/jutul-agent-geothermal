from __future__ import annotations

import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlencode

import geopandas as gpd
import pandas as pd
import requests
from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pyproj import Transformer

WFS_BASE_URL = "https://wfs.geonorge.no/skwms1/wfs.matrikkelen-bygningspunkt"

# UTM zone 33 is used as the default; could be chosen dynamically based on longitude.
DEFAULT_EPSG = 25833

DEFAULT_RADIUS_M = 50.0
MAX_RADIUS_M = 200.0

_cached_typename: str | None = None
_cached_type_map: dict[str, dict] | None = None

router = APIRouter()


class BuildingInfo(BaseModel):
    bygningsnummer: str
    bygningstype: str | None = None
    bygningsstatus: str | None = None
    kommunenummer: str | None = None
    kommunenavn: str | None = None
    lat: float
    lon: float
    distance_m: float

    # Placeholders for future MatrikkelAPI extended access
    bruksareal_totalt: float | None = None
    bruksareal_til_bolig: float | None = None
    bruksareal_til_annet: float | None = None
    antall_boenheter: int | None = None


class BuildingClickResponse(BaseModel):
    hit: bool
    click_lat: float
    click_lon: float
    radius_m: float
    selected: BuildingInfo | None
    candidates: list[BuildingInfo]


app = FastAPI(title="WFS building click API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


def get_wfs_typename() -> str:
    """Fetch GetCapabilities and find the correct feature type name.

    Result is cached so only one network call is made per process lifetime.
    """
    global _cached_typename
    if _cached_typename is not None:
        return _cached_typename

    r = requests.get(
        WFS_BASE_URL,
        params={"service": "WFS", "request": "GetCapabilities"},
        timeout=30,
    )
    r.raise_for_status()

    root = ET.fromstring(r.content)
    names: list[str] = []

    for elem in root.findall(
        ".//wfs:FeatureType/wfs:Name",
        {"wfs": "http://www.opengis.net/wfs/2.0", "ows": "http://www.opengis.net/ows/1.1"},
    ):
        if elem.text:
            names.append(elem.text)

    if not names:
        # Older WFS servers use the WFS 1.x namespace
        for elem in root.findall(
            ".//{http://www.opengis.net/wfs}FeatureType/{http://www.opengis.net/wfs}Name"
        ):
            if elem.text:
                names.append(elem.text)

    if not names:
        raise RuntimeError("No FeatureType names found in WFS GetCapabilities.")

    for name in names:
        if "bygning" in name.lower() or "building" in name.lower():
            _cached_typename = name
            return name

    _cached_typename = names[0]
    return names[0]


def make_bbox_utm(
    lat: float,
    lon: float,
    radius_m: float,
    epsg: int = DEFAULT_EPSG,
) -> tuple[float, float, float, float]:
    """Return a square bounding box in UTM coordinates centred on (lat, lon)."""
    transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    x, y = transformer.transform(lon, lat)
    return x - radius_m, y - radius_m, x + radius_m, y + radius_m


def _first_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """Return the first candidate column name that exists in df, case-insensitively."""
    lower_to_actual = {c.lower(): c for c in df.columns}
    for candidate in candidates:
        actual = lower_to_actual.get(candidate.lower())
        if actual:
            return actual
    return None


def fetch_building_points_from_wfs(
    lat: float,
    lon: float,
    radius_m: float,
    epsg: int = DEFAULT_EPSG,
) -> gpd.GeoDataFrame:
    """Query Matrikkelen Bygningspunkt WFS with a bounding box around the click point.

    Returns a GeoDataFrame of building points in the area.
    """
    type_name = get_wfs_typename()
    minx, miny, maxx, maxy = make_bbox_utm(lat, lon, radius_m, epsg)

    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": type_name,
        "srsName": f"EPSG:{epsg}",
        "bbox": f"{minx},{miny},{maxx},{maxy},EPSG:{epsg}",
    }

    r = requests.get(f"{WFS_BASE_URL}?{urlencode(params)}", timeout=60)
    r.raise_for_status()

    if not r.content:
        return gpd.GeoDataFrame(geometry=[], crs=f"EPSG:{epsg}")

    # Write to a temp file — more robust than streaming GML directly into GeoPandas/Fiona.
    with tempfile.NamedTemporaryFile(suffix=".gml", delete=False) as tmp:
        tmp.write(r.content)
        tmp_path = Path(tmp.name)

    try:
        gdf = gpd.read_file(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    if gdf.empty:
        return gdf

    return gdf.set_crs(epsg=epsg) if gdf.crs is None else gdf.to_crs(epsg=epsg)


BUILDING_TYPE_CODELIST_URL = (
    "https://register.geonorge.no/api/sosi-kodelister/kartdata/bygningstypekode.json"
)


def fetch_building_type_codelist() -> dict[str, dict]:
    """Fetch the BygningstypeKode code list from Geonorge Register.

    Returns a mapping from code → {name, description, status, id}.
    """
    response = requests.get(BUILDING_TYPE_CODELIST_URL, timeout=30)
    response.raise_for_status()

    data = response.json()
    items = data.get("containeditems", [])

    if not items:
        raise RuntimeError("No code values found in the BygningstypeKode response.")

    code_map: dict[str, dict] = {}
    for item in items:
        code = str(item.get("codevalue", "")).strip()
        if not code:
            continue
        code_map[code] = {
            "name": item.get("label"),
            "description": item.get("description"),
            "status": item.get("status"),
            "id": item.get("id"),
        }

    return code_map


def get_building_type_codelist() -> dict[str, dict]:
    """Return the cached code list, fetching from Geonorge on the first call.

    On network failure an empty dict is returned and the raw code is used as a fallback.
    """
    global _cached_type_map
    if _cached_type_map is not None:
        return _cached_type_map
    try:
        _cached_type_map = fetch_building_type_codelist()
    except Exception:
        _cached_type_map = {}
    return _cached_type_map


def get_building_type_name(code: int | str | None, code_map: dict[str, dict]) -> str | None:
    """Look up the building type name for a given code.

    Returns None if the code is missing, or the raw code string as a fallback if the
    lookup fails (e.g. the code list could not be fetched).
    """
    if code is None:
        return None
    code_str = str(code).strip()
    if not code_str:
        return None
    item = code_map.get(code_str)
    if item is None:
        # Code list unavailable or code unknown — show the raw code.
        return code_str
    return item.get("name") or code_str


def normalize_building_candidates(
    gdf: gpd.GeoDataFrame,
    click_lat: float,
    click_lon: float,
    epsg: int = DEFAULT_EPSG,
) -> list[BuildingInfo]:
    """Convert a WFS GeoDataFrame to a list of BuildingInfo, sorted by distance."""
    if gdf.empty:
        return []

    col_nr = _first_column(
        gdf,
        [
            "bygningsnummer",
            "bygningsnr",
            "bygningnummer",
            "byggnr",
            "BYGGNR",
            "bygningsNummer",
            "bygning_nummer",
        ],
    )
    if col_nr is None:
        raise RuntimeError(f"Building number column not found. WFS columns: {list(gdf.columns)}")

    col_type = _first_column(
        gdf, ["bygningstype", "bygningstypekode", "byggtype", "BYGGTYP_NBR", "bygningstypeKode"]
    )
    col_status = _first_column(
        gdf, ["bygningsstatus", "bygningstatus", "byggstatus", "BYGGSTAT", "bygningsstatusKode"]
    )
    col_kommnr = _first_column(gdf, ["kommunenummer", "kommunenr", "kommune_nr", "KOMM"])
    col_kommnm = _first_column(gdf, ["kommunenavn", "kommune", "kommune_navn"])

    transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    click_x, click_y = transformer.transform(click_lon, click_lat)
    click_point = gpd.GeoSeries.from_xy([click_x], [click_y], crs=f"EPSG:{epsg}").iloc[0]

    gdf = gdf.copy()
    gdf["distance_m"] = gdf.geometry.distance(click_point)
    gdf_wgs84 = gdf.to_crs("EPSG:4326")

    type_map = get_building_type_codelist()

    def _str(row: pd.Series, col: str | None) -> str | None:
        if col is None or pd.isna(row[col]):
            return None
        return str(row[col])

    results: list[BuildingInfo] = []
    for idx, row in gdf.sort_values("distance_m").iterrows():
        point = gdf_wgs84.loc[idx].geometry.centroid
        raw_type = _str(row, col_type)
        results.append(
            BuildingInfo(
                bygningsnummer=str(row[col_nr]),
                bygningstype=get_building_type_name(raw_type, type_map),
                bygningsstatus=_str(row, col_status),
                kommunenummer=_str(row, col_kommnr),
                kommunenavn=_str(row, col_kommnm),
                lat=float(point.y),
                lon=float(point.x),
                distance_m=float(row["distance_m"]),
            )
        )

    return results


def get_building_info_from_wfs_click(
    lat: float,
    lon: float,
    radius_m: float = DEFAULT_RADIUS_M,
    max_candidates: int = 10,
) -> BuildingClickResponse:
    """Main entry point: click lat/lon → WFS BBOX → candidate buildings → selected building."""
    radius_m = min(float(radius_m), MAX_RADIUS_M)
    query_radius_m = max(radius_m, 15.0)

    gdf = fetch_building_points_from_wfs(lat, lon, query_radius_m)
    candidates = normalize_building_candidates(gdf, click_lat=lat, click_lon=lon)
    candidates = [c for c in candidates if c.distance_m <= radius_m][:max_candidates]
    selected = candidates[0] if candidates else None

    return BuildingClickResponse(
        hit=selected is not None,
        click_lat=lat,
        click_lon=lon,
        radius_m=radius_m,
        selected=selected,
        candidates=candidates,
    )


@router.get("/api/building-click", response_model=BuildingClickResponse)
def api_building_click(
    lat: float = Query(...),
    lon: float = Query(...),
    radius_m: float = Query(DEFAULT_RADIUS_M, ge=1, le=MAX_RADIUS_M),
    max_candidates: int = Query(10, ge=1, le=50),
) -> BuildingClickResponse:
    result = get_building_info_from_wfs_click(
        lat=lat, lon=lon, radius_m=radius_m, max_candidates=max_candidates
    )
    if not result.hit:
        raise HTTPException(
            status_code=404,
            detail={
                "message": "No building point found within radius.",
                "lat": lat,
                "lon": lon,
                "radius_m": radius_m,
            },
        )
    return result


@router.get("/api/health")
def health() -> dict:
    return {"status": "ok", "source": "Matrikkelen Bygningspunkt WFS", "wfs": WFS_BASE_URL}
