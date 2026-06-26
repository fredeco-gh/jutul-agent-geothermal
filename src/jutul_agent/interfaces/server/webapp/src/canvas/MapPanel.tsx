// A MapLibre map as a native canvas panel — the simulator-agnostic seam an
// extension's own capability drives via `ui`/`ui_event` (see docs/web-ui.md's
// "Extending the canvas"). This skeleton renders an empty map and proves the
// wire: a click reports its coordinates as a `ui_event`, and a `fly_to` action
// targeted at this view (via useUiActions) moves the camera. No geothermal
// data or styling lives here yet — that is layered on in a later phase.

import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef, useState } from "react";

import type { PanelProps } from "./registry";
import { useUiActions } from "./registry";

const EMPTY_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {},
  layers: [],
};

export function MapPanel({ view, active, onLoaded, onUiEvent }: PanelProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const uiActions = useUiActions(view.id);
  // Phase 0 has no basemap, so panning/zooming the empty style is otherwise
  // invisible — this readout is the manual-verification aid, not part of the
  // panel's real UI. Drop it once Phase 1 gives the map actual content to look at.
  const [hud, setHud] = useState({ lng: 0, lat: 0, zoom: 1, clicks: 0 });

  useEffect(() => {
    if (!containerRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: EMPTY_STYLE,
      center: [0, 0],
      zoom: 1,
    });
    map.on("load", onLoaded);
    map.on("move", () => {
      const c = map.getCenter();
      setHud((h) => ({ ...h, lng: c.lng, lat: c.lat, zoom: map.getZoom() }));
    });
    map.on("click", (e) => {
      setHud((h) => ({ ...h, clicks: h.clicks + 1 }));
      onUiEvent({ action: "click", lng: e.lngLat.lng, lat: e.lngLat.lat });
    });
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
    // Mounted once for this view's lifetime; onLoaded/onUiEvent are
    // Canvas-supplied closures stable enough for the panel's own life.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view.id]);

  // MapLibre measures its container once, at construction — a panel mounted
  // while hidden (the canvas keeps every tab mounted, toggling `display`) gets
  // sized 0x0 until told to remeasure on becoming the active tab.
  useEffect(() => {
    if (active) mapRef.current?.resize();
  }, [active]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    for (const { action, payload } of uiActions) {
      if (action === "fly_to") {
        const { lng, lat, zoom } = payload as { lng?: number; lat?: number; zoom?: number };
        if (typeof lng === "number" && typeof lat === "number") {
          const z = zoom ?? map.getZoom();
          map.flyTo({ center: [lng, lat], zoom: z });
          setHud((h) => ({ ...h, lng, lat, zoom: z }));
        }
      }
    }
  }, [uiActions]);

  return (
    <div className={`map-panel${active ? " active" : ""}`} style={{ position: "relative" }}>
      <div ref={containerRef} style={{ position: "absolute", inset: 0 }} />
      <div
        style={{
          position: "absolute",
          top: 8,
          left: 8,
          zIndex: 1,
          padding: "4px 8px",
          background: "rgba(0,0,0,0.65)",
          color: "#fff",
          font: "12px monospace",
          borderRadius: 4,
          pointerEvents: "none",
        }}
      >
        lng {hud.lng.toFixed(3)} · lat {hud.lat.toFixed(3)} · zoom {hud.zoom.toFixed(1)} · clicks{" "}
        {hud.clicks}
      </div>
    </div>
  );
}
