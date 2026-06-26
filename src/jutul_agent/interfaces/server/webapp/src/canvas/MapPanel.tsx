// The geothermal map as a native canvas panel — see docs/web-ui.md's
// "Extending the canvas". Ported from geothermal-viz's web/js/app.js
// (rendering: layers, popups, well info, terrain/3D buildings) onto the
// generic `ui`/`ui_event` wire Phase 0 proved (canvas/registry.tsx's
// useUiActions/onUiEvent): a tool drives the map by sending a `ui` action
// targeted at this view (see examples/geothermal-map/capability.py), and a
// well click is relayed back as a `ui_event`, the same way geothermal-viz's
// jutul-agent-bridge.js used to relay it over postMessage.
//
// Borehole data is fetched directly from a static mount (examples/geothermal-map
// /serve.py's `extra_mounts`) rather than through any session/Julia kernel —
// a missing or broken mount must not break the rest of the app, so a failed
// fetch just leaves the map without well markers (see the principle in
// docs/web-ui.md).

import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef, useState } from "react";

import "./MapPanel.css";
import type { PanelProps } from "./registry";
import { useUiActions } from "./registry";

interface GeoJsonFeature {
  type: "Feature";
  geometry: { type: string; coordinates: [number, number] };
  properties: Record<string, unknown>;
}

interface GeoJsonFeatureCollection {
  type: "FeatureCollection";
  features: GeoJsonFeature[];
}

const DATA_URL = "/geothermal-data/all_boreholes.geojson";

const MAP_CENTER: [number, number] = [10.75, 59.91]; // Oslo
const MAP_ZOOM = 11;

interface LayerConfig {
  id: string;
  color: string;
  label: string;
}

// Norwegian source layer name -> the group it renders as (several minor
// layers share the "other" group's source/layer/checkbox).
const LAYER_CONFIG: Record<string, LayerConfig> = {
  EnergiBrønn: { id: "energibronn", color: "#e74c3c", label: "Energy Well" },
  GrunnvannBrønn: { id: "grunnvannbronn", color: "#3498db", label: "Groundwater Well" },
  BrønnPark: { id: "bronnpark", color: "#2ecc71", label: "Well Park" },
  Sonderboring: { id: "sonderboring", color: "#f39c12", label: "Probe Drilling" },
  LGNBrønn: { id: "other", color: "#9b59b6", label: "LGN Well" },
  GrunnvannOppkomme: { id: "other", color: "#9b59b6", label: "Spring" },
  LGNOmrådeRefPkt: { id: "other", color: "#9b59b6", label: "LGN Ref. Point" },
};

// One toggle per group shown in the sidebar.
const LAYER_GROUPS: LayerConfig[] = [
  { id: "energibronn", color: "#e74c3c", label: "Energy Wells (EnergiBrønn)" },
  { id: "grunnvannbronn", color: "#3498db", label: "Groundwater Wells (GrunnvannBrønn)" },
  { id: "bronnpark", color: "#2ecc71", label: "Well Parks (BrønnPark)" },
  { id: "sonderboring", color: "#f39c12", label: "Probe Drillings (Sonderboring)" },
  { id: "other", color: "#9b59b6", label: "Other (LGN, Springs)" },
];

// Norwegian -> English field labels for the well-info table.
const FIELD_LABELS: Record<string, string> = {
  brønnNr: "Well No.",
  objekttype: "Type",
  boretLengde: "Drilled Length (m)",
  boretLengdeTilBerg: "Depth to Bedrock (m)",
  boreDato: "Drill Date",
  diameterBorehull: "Borehole Diameter (mm)",
  vannstandBorehull: "Water Level (m)",
  boretKapasitet: "Capacity (l/h)",
  materialForingsrør: "Casing Material",
  lengdeForingsrør: "Casing Length (m)",
  brønnHelningType: "Inclination Type",
  boretHelningsgrad: "Inclination (°)",
  boretAzimuth: "Azimuth (°)",
  oppdragstaker: "Contractor",
  konsulentFirma: "Consultant",
  beskrivelse: "Description",
  brønnParkNr: "Well Park No.",
  brønnpOmrNavn: "Area Name",
  antallEnergiBrønner: "No. of Energy Wells",
  brønnpVEffekt: "Heating Power (kW)",
  brønnpVEnergi: "Heating Energy (MWh)",
  brønnpKEffekt: "Cooling Power (kW)",
  brønnpKEnergi: "Cooling Energy (MWh)",
  brønnpFrikjøling: "Free Cooling",
  brønnpKollVæske: "Collector Fluid",
  geolMedium: "Geological Medium",
};

interface SelectedWell {
  title: string;
  color: string;
  label: string;
  rows: Array<[string, string]>;
}

function escapeHtml(value: unknown): string {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function formatDate(value: unknown): string {
  if (!value) return "";
  const d = new Date(String(value));
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleDateString("en-GB", { year: "numeric", month: "short", day: "numeric" });
}

function describeFeature(props: Record<string, unknown>): { title: string; color: string; label: string } {
  const layerName = String(props.layer || "Unknown");
  const cfg = LAYER_CONFIG[layerName] ?? { id: "other", color: "#999", label: layerName };
  const title = props.brønnNr
    ? `Well #${props.brønnNr}`
    : props.brønnParkNr
      ? `Well Park #${props.brønnParkNr}`
      : cfg.label;
  return { title, color: cfg.color, label: cfg.label };
}

const MAP_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    "osm-raster": {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: '&copy; OpenStreetMap contributors',
    },
  },
  layers: [{ id: "osm-base", type: "raster", source: "osm-raster", minzoom: 0, maxzoom: 19 }],
};

export function MapPanel({ view, active, onLoaded, onUiEvent }: PanelProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const popupRef = useRef<maplibregl.Popup | null>(null);
  const selectWellRef = useRef<(feature: GeoJsonFeature, lngLat: { lng: number; lat: number }) => void>(
    () => {},
  );
  const uiActions = useUiActions(view.id);

  const [selected, setSelected] = useState<SelectedWell | null>(null);
  const [total, setTotal] = useState(0);
  const [byGroup, setByGroup] = useState<Record<string, number>>({});
  const [visibility, setVisibility] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(LAYER_GROUPS.map((g) => [g.id, true])),
  );
  const [collapsed, setCollapsed] = useState(false);

  // A ref (not a plain function) so the mount effect below — which only runs
  // once per view.id — always calls the latest version, without needing to
  // depend on (and re-run for) every state setter it closes over.
  selectWellRef.current = (feature, lngLat) => {
    const props = feature.properties;
    const { title, color, label } = describeFeature(props);

    popupRef.current?.remove();
    const map = mapRef.current;
    if (map) {
      popupRef.current = new maplibregl.Popup({ offset: [0, 10], anchor: "top", maxWidth: "300px" })
        .setLngLat(lngLat)
        .setHTML(
          `<div class="popup-title">${escapeHtml(title)}</div>` +
            `<span class="popup-type" style="background:${color}">${escapeHtml(label)}</span>` +
            `<div class="popup-detail">` +
            (props.boretLengde ? `Depth: ${escapeHtml(props.boretLengde)} m<br>` : "") +
            (props.boreDato ? `Drilled: ${escapeHtml(formatDate(props.boreDato))}<br>` : "") +
            (props.oppdragstaker ? `Contractor: ${escapeHtml(props.oppdragstaker)}` : "") +
            `</div>`,
        )
        .addTo(map);
    }

    const rows: Array<[string, string]> = [];
    for (const [key, value] of Object.entries(props)) {
      if (key === "layer" || value === null || value === undefined || value === "") continue;
      const fieldLabel = FIELD_LABELS[key] || key;
      const display =
        key.toLowerCase().includes("dato") || key.toLowerCase().includes("date")
          ? formatDate(value)
          : String(value);
      rows.push([fieldLabel, display]);
    }
    setSelected({ title, color, label, rows });

    // Relay the selection to the agent — mirrors geothermal-viz's own
    // wellSelected event (jutul-agent-bridge.js used to forward it over
    // postMessage); now it's a plain ui_event over the session's own socket.
    onUiEvent({ event: "wellSelected", properties: props, lngLat });
  };

  useEffect(() => {
    if (!containerRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: MAP_STYLE,
      center: MAP_CENTER,
      zoom: MAP_ZOOM,
      pitch: 45,
      bearing: -10,
      maxZoom: 18,
      minZoom: 8,
      maxPitch: 70,
    });
    map.addControl(new maplibregl.NavigationControl(), "top-right");
    map.addControl(new maplibregl.ScaleControl({ maxWidth: 200 }), "bottom-right");
    mapRef.current = map;

    let loaded = false;
    const finishLoading = () => {
      if (loaded) return;
      loaded = true;
      onLoaded();
    };
    // Tied to the style finishing (not the data fetch below), so a slow or
    // broken data fetch can't strand the canvas's loading spinner.
    map.on("load", finishLoading);

    map.once("style.load", () => {
      fetch(DATA_URL)
        .then((resp) => {
          if (!resp.ok) throw new Error(`status ${resp.status}`);
          return resp.json() as Promise<GeoJsonFeatureCollection>;
        })
        .then((geojson) => {
          const groups: Record<string, { features: GeoJsonFeature[]; color: string }> = {};
          for (const group of LAYER_GROUPS) groups[group.id] = { features: [], color: group.color };
          for (const feature of geojson.features) {
            const layerName = String(feature.properties.layer || "unknown");
            const cfg = LAYER_CONFIG[layerName];
            if (cfg && groups[cfg.id]) groups[cfg.id].features.push(feature);
          }

          for (const [groupId, group] of Object.entries(groups)) {
            const sourceId = `source-${groupId}`;
            const layerId = `layer-${groupId}`;
            map.addSource(sourceId, {
              type: "geojson",
              data: { type: "FeatureCollection", features: group.features },
            });
            map.addLayer({
              id: layerId,
              type: "circle",
              source: sourceId,
              paint: {
                "circle-radius": ["interpolate", ["linear"], ["zoom"], 8, 2, 12, 5, 16, 10],
                "circle-color": group.color,
                "circle-opacity": 0.8,
                "circle-stroke-width": 1,
                "circle-stroke-color": "#ffffff",
              },
            });
            map.on("mouseenter", layerId, () => {
              map.getCanvas().style.cursor = "pointer";
            });
            map.on("mouseleave", layerId, () => {
              map.getCanvas().style.cursor = "";
            });
            map.on("click", layerId, (e) => {
              const feature = e.features?.[0];
              if (feature) selectWellRef.current(feature as unknown as GeoJsonFeature, e.lngLat);
            });
          }

          setTotal(geojson.features.length);
          setByGroup(Object.fromEntries(Object.entries(groups).map(([id, g]) => [id, g.features.length])));

          // Terrain/3D buildings are visual polish on free, keyless public
          // tile sources — best-effort, since the map is fully usable without
          // them if a source ever changes shape or goes away.
          try {
            map.addSource("terrain-source", {
              type: "raster-dem",
              tiles: ["https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"],
              tileSize: 256,
              encoding: "terrarium",
            });
            map.setTerrain({ source: "terrain-source", exaggeration: 1.5 });
          } catch (err) {
            console.warn("Could not enable terrain:", err);
          }
          try {
            map.addSource("openmaptiles", { type: "vector", url: "https://tiles.openfreemap.org/planet" });
            map.addLayer({
              id: "3d-buildings",
              source: "openmaptiles",
              "source-layer": "building",
              type: "fill-extrusion",
              minzoom: 14,
              paint: {
                "fill-extrusion-color": "#ddd",
                "fill-extrusion-height": ["get", "render_height"],
                "fill-extrusion-base": ["get", "render_min_height"],
                "fill-extrusion-opacity": 0.6,
              },
            });
          } catch (err) {
            console.warn("Could not add 3D buildings:", err);
          }
        })
        .catch((err) => {
          // A missing/broken data mount must not break the rest of the app —
          // the map still renders, just with no well markers.
          console.warn("Could not load borehole data:", err);
        })
        .finally(finishLoading);
    });

    return () => {
      map.remove();
      mapRef.current = null;
      popupRef.current = null;
    };
    // Mounted once for this view's lifetime; onLoaded/onUiEvent are
    // Canvas-supplied closures stable enough for the panel's own life, and
    // selectWellRef always points at the current closure (see above).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view.id]);

  useEffect(() => {
    if (active) mapRef.current?.resize();
  }, [active]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    for (const { action, payload } of uiActions) {
      if (action === "set_map_view") {
        const { lon, lat, zoom } = payload as { lon?: number; lat?: number; zoom?: number };
        if (typeof lon === "number" && typeof lat === "number") {
          map.flyTo({ center: [lon, lat], zoom: zoom ?? map.getZoom() });
        }
      } else if (action === "go_to_well") {
        const { lon, lat, feature } = payload as {
          lon?: number;
          lat?: number;
          feature?: GeoJsonFeature;
        };
        if (typeof lon === "number" && typeof lat === "number") {
          map.flyTo({ center: [lon, lat], zoom: 17 });
          if (feature) selectWellRef.current(feature, { lng: lon, lat });
        }
      }
    }
  }, [uiActions]);

  const toggleLayer = (groupId: string, checked: boolean) => {
    setVisibility((v) => ({ ...v, [groupId]: checked }));
    const map = mapRef.current;
    const layerId = `layer-${groupId}`;
    if (map?.getLayer(layerId)) {
      map.setLayoutProperty(layerId, "visibility", checked ? "visible" : "none");
    }
  };

  const visibleCount = LAYER_GROUPS.reduce(
    (sum, g) => sum + (visibility[g.id] ? byGroup[g.id] ?? 0 : 0),
    0,
  );

  return (
    <div className={`map-panel${active ? " active" : ""}`}>
      <div ref={containerRef} className="map-panel-map" />
      <div className={`sidebar${collapsed ? " collapsed" : ""}`}>
        <div className="sidebar-header">
          <h1>Geothermal map</h1>
          <p className="subtitle">Norwegian boreholes</p>
        </div>
        <div className="sidebar-section">
          <h2>Layers</h2>
          {LAYER_GROUPS.map((g) => (
            <label className="layer-toggle" key={g.id}>
              <input
                type="checkbox"
                checked={visibility[g.id] ?? true}
                onChange={(e) => toggleLayer(g.id, e.target.checked)}
              />
              <span className="color-dot" style={{ background: g.color }} />
              {g.label}
            </label>
          ))}
        </div>
        <div className="sidebar-section">
          <h2>Statistics</h2>
          <div className="stat-item">
            <span className="stat-label">Total boreholes:</span>
            <span className="stat-value">{total.toLocaleString()}</span>
          </div>
          <div className="stat-item">
            <span className="stat-label">Visible:</span>
            <span className="stat-value">{visibleCount.toLocaleString()}</span>
          </div>
        </div>
        <div className="sidebar-section">
          <h2>Selected Well</h2>
          {selected ? (
            <div className="well-detail">
              <div className="well-title">
                <span className="popup-type" style={{ background: selected.color }}>
                  {selected.label}
                </span>{" "}
                {selected.title}
              </div>
              <table>
                <tbody>
                  {selected.rows.map(([label, value]) => (
                    <tr key={label}>
                      <td>{label}</td>
                      <td>{value}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="no-selection">Click a well on the map to view details.</p>
          )}
        </div>
      </div>
      <button
        className={`sidebar-toggle${collapsed ? " shifted" : ""}`}
        title="Toggle sidebar"
        onClick={() => setCollapsed((c) => !c)}
      >
        ☰
      </button>
    </div>
  );
}
