import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SessionProvider } from "../context";
import { Controller } from "../controller";
import { createSessionStore } from "../store";
import type { SessionStore, View } from "../store";
import type { StoreApi } from "zustand/vanilla";
import { MapPanel } from "./MapPanel";

// maplibre-gl needs a real WebGL context, which jsdom doesn't provide — stand
// in a fake that records what the panel does, instead of what it renders.
// `vi.mock`'s factory is hoisted above this file's own declarations, so the
// class must be created through `vi.hoisted` to be visible inside it.
const { FakeMap, FakePopup } = vi.hoisted(() => {
  class FakeMap {
    static instances: FakeMap[] = [];
    handlers: Record<string, Array<(e: unknown) => void>> = {};
    layers = new Set<string>();
    layoutProps: Array<{ id: string; prop: string; value: unknown }> = [];
    removed = false;
    flyToCalls: unknown[] = [];
    constructor(public options: unknown) {
      FakeMap.instances.push(this);
    }
    addControl() {}
    on(event: string, a: unknown, b?: unknown) {
      const key = typeof a === "string" ? `${event}:${a}` : event;
      const cb = (typeof a === "string" ? b : a) as (e: unknown) => void;
      (this.handlers[key] ??= []).push(cb);
    }
    once(event: string, cb: (e: unknown) => void) {
      (this.handlers[event] ??= []).push(cb);
    }
    fire(event: string, e: unknown = {}) {
      for (const cb of this.handlers[event] ?? []) cb(e);
    }
    fireLayer(event: string, layerId: string, e: unknown = {}) {
      for (const cb of this.handlers[`${event}:${layerId}`] ?? []) cb(e);
    }
    addSource() {}
    addLayer(def: { id: string }) {
      this.layers.add(def.id);
    }
    getLayer(id: string) {
      return this.layers.has(id) ? {} : undefined;
    }
    setLayoutProperty(id: string, prop: string, value: unknown) {
      this.layoutProps.push({ id, prop, value });
    }
    getCanvas() {
      return { style: {} as Record<string, string> };
    }
    setTerrain() {}
    remove() {
      this.removed = true;
    }
    resize() {}
    getZoom() {
      return 1;
    }
    flyTo(opts: unknown) {
      this.flyToCalls.push(opts);
    }
  }
  class FakePopup {
    lngLat: unknown;
    html = "";
    removed = false;
    setLngLat(lngLat: unknown) {
      this.lngLat = lngLat;
      return this;
    }
    setHTML(html: string) {
      this.html = html;
      return this;
    }
    addTo() {
      return this;
    }
    remove() {
      this.removed = true;
    }
  }
  return { FakeMap, FakePopup };
});

vi.mock("maplibre-gl", () => ({
  default: {
    Map: FakeMap,
    Popup: FakePopup,
    NavigationControl: class {},
    ScaleControl: class {},
  },
}));

const SAMPLE_GEOJSON = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      geometry: { type: "Point", coordinates: [10.7, 59.9] },
      properties: { layer: "EnergiBrønn", brønnNr: "100", oppdragstaker: "Acme" },
    },
    {
      type: "Feature",
      geometry: { type: "Point", coordinates: [10.8, 60.0] },
      properties: { layer: "BrønnPark", brønnParkNr: "200" },
    },
  ],
};

function makeView(id: string): View {
  return { id, url: "", title: "Map", kind: "map", nonce: 0 };
}

function renderPanel(view: View) {
  const store: StoreApi<SessionStore> = createSessionStore();
  const controller = new Controller(store);
  const onUiEvent = vi.fn();
  const onLoaded = vi.fn();
  const utils = render(
    <SessionProvider value={{ store, controller }}>
      <MapPanel view={view} active reloadToken={0} onLoaded={onLoaded} onUiEvent={onUiEvent} />
    </SessionProvider>,
  );
  return { store, onUiEvent, onLoaded, ...utils };
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("MapPanel", () => {
  beforeEach(() => {
    FakeMap.instances.length = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, json: async () => SAMPLE_GEOJSON }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("calls onLoaded on the map's load event, independent of the data fetch", () => {
    const { onLoaded } = renderPanel(makeView("slot:geothermal-map"));
    const map = FakeMap.instances.at(-1)!;
    expect(onLoaded).not.toHaveBeenCalled();
    act(() => map.fire("load"));
    expect(onLoaded).toHaveBeenCalledTimes(1);
  });

  it("fetches the borehole data and adds one source/layer per layer group", async () => {
    renderPanel(makeView("slot:geothermal-map"));
    const map = FakeMap.instances.at(-1)!;
    act(() => map.fire("style.load"));
    await flush();
    expect(fetch).toHaveBeenCalledWith("/geothermal-data/all_boreholes.geojson");
    expect(map.layers.has("layer-energibronn")).toBe(true);
    expect(map.layers.has("layer-bronnpark")).toBe(true);
    expect(screen.getByText("Total boreholes:").nextSibling).toHaveTextContent("2");
  });

  it("still calls onLoaded if the data fetch fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({}) }));
    const { onLoaded } = renderPanel(makeView("slot:geothermal-map"));
    const map = FakeMap.instances.at(-1)!;
    act(() => map.fire("load"));
    act(() => map.fire("style.load"));
    await flush();
    expect(onLoaded).toHaveBeenCalledTimes(1);
  });

  it("selecting a well via a layer click shows its info and emits a ui_event", async () => {
    const { onUiEvent } = renderPanel(makeView("slot:geothermal-map"));
    const map = FakeMap.instances.at(-1)!;
    act(() => map.fire("style.load"));
    await flush();

    act(() =>
      map.fireLayer("click", "layer-energibronn", {
        lngLat: { lng: 10.7, lat: 59.9 },
        features: [SAMPLE_GEOJSON.features[0]],
      }),
    );

    expect(screen.getByText("Well #100")).toBeInTheDocument();
    expect(onUiEvent).toHaveBeenCalledWith({
      event: "wellSelected",
      properties: SAMPLE_GEOJSON.features[0].properties,
      lngLat: { lng: 10.7, lat: 59.9 },
    });
  });

  it("moves the camera on a set_map_view action targeted at this view", () => {
    const view = makeView("slot:geothermal-map");
    const { store } = renderPanel(view);
    const map = FakeMap.instances.at(-1)!;
    act(() => {
      store.getState().handle({
        type: "ui",
        action: "set_map_view",
        payload: { lon: 5, lat: 6, zoom: 9 },
        target: view.id,
      });
    });
    expect(map.flyToCalls).toEqual([{ center: [5, 6], zoom: 9 }]);
  });

  it("a go_to_well action flies to and selects the resolved feature", () => {
    const view = makeView("slot:geothermal-map");
    const { store, onUiEvent } = renderPanel(view);
    const map = FakeMap.instances.at(-1)!;
    const feature = SAMPLE_GEOJSON.features[0];
    act(() => {
      store.getState().handle({
        type: "ui",
        action: "go_to_well",
        payload: { lon: 10.7, lat: 59.9, feature },
        target: view.id,
      });
    });
    expect(map.flyToCalls).toEqual([{ center: [10.7, 59.9], zoom: 17 }]);
    expect(screen.getByText("Well #100")).toBeInTheDocument();
    expect(onUiEvent).toHaveBeenCalledWith({
      event: "wellSelected",
      properties: feature.properties,
      lngLat: { lng: 10.7, lat: 59.9 },
    });
  });

  it("toggling a layer checkbox hides that layer on the map", async () => {
    renderPanel(makeView("slot:geothermal-map"));
    const map = FakeMap.instances.at(-1)!;
    act(() => map.fire("style.load"));
    await flush();

    const label = screen.getByText(/Energy Wells/);
    const checkbox = label.querySelector("input") as HTMLInputElement;
    fireEvent.click(checkbox);
    expect(map.layoutProps).toEqual([{ id: "layer-energibronn", prop: "visibility", value: "none" }]);
  });

  it("removes the map on unmount", () => {
    const { unmount } = renderPanel(makeView("slot:geothermal-map"));
    const map = FakeMap.instances.at(-1)!;
    unmount();
    expect(map.removed).toBe(true);
  });
});
