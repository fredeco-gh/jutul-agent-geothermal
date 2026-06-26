import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

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
const { FakeMap } = vi.hoisted(() => {
  class FakeMap {
    static instances: FakeMap[] = [];
    handlers: Record<string, Array<(e: unknown) => void>> = {};
    removed = false;
    resizeCalls = 0;
    flyToCalls: unknown[] = [];
    constructor(public options: unknown) {
      FakeMap.instances.push(this);
    }
    on(event: string, cb: (e: unknown) => void) {
      (this.handlers[event] ??= []).push(cb);
    }
    fire(event: string, e: unknown = {}) {
      for (const cb of this.handlers[event] ?? []) cb(e);
    }
    remove() {
      this.removed = true;
    }
    resize() {
      this.resizeCalls++;
    }
    getZoom() {
      return 1;
    }
    flyTo(opts: unknown) {
      this.flyToCalls.push(opts);
    }
  }
  return { FakeMap };
});

vi.mock("maplibre-gl", () => ({ default: { Map: FakeMap } }));

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

describe("MapPanel", () => {
  it("mounts an empty map and calls onLoaded on the map's load event", () => {
    FakeMap.instances.length = 0;
    const { onLoaded } = renderPanel(makeView("slot:map"));
    const map = FakeMap.instances.at(-1)!;
    expect(onLoaded).not.toHaveBeenCalled();
    act(() => map.fire("load"));
    expect(onLoaded).toHaveBeenCalledTimes(1);
  });

  it("reports a click as a ui_event with the clicked coordinates", () => {
    FakeMap.instances.length = 0;
    const { onUiEvent } = renderPanel(makeView("slot:map"));
    const map = FakeMap.instances.at(-1)!;
    act(() => map.fire("click", { lngLat: { lng: 10, lat: 20 } }));
    expect(onUiEvent).toHaveBeenCalledWith({ action: "click", lng: 10, lat: 20 });
  });

  it("the debug HUD's click counter increments on each click", () => {
    FakeMap.instances.length = 0;
    renderPanel(makeView("slot:map"));
    const map = FakeMap.instances.at(-1)!;
    expect(screen.getByText(/clicks 0/)).toBeInTheDocument();
    act(() => map.fire("click", { lngLat: { lng: 1, lat: 2 } }));
    act(() => map.fire("click", { lngLat: { lng: 3, lat: 4 } }));
    expect(screen.getByText(/clicks 2/)).toBeInTheDocument();
  });

  it("the debug HUD reflects the camera after a fly_to action", () => {
    FakeMap.instances.length = 0;
    const view = makeView("slot:map");
    const { store } = renderPanel(view);
    act(() => {
      store.getState().handle({
        type: "ui",
        action: "fly_to",
        payload: { lng: 12.5, lat: -3.25, zoom: 7 },
        target: view.id,
      });
    });
    expect(screen.getByText(/lng 12\.500/)).toBeInTheDocument();
    expect(screen.getByText(/lat -3\.250/)).toBeInTheDocument();
    expect(screen.getByText(/zoom 7\.0/)).toBeInTheDocument();
  });

  it("moves the camera on a fly_to action targeted at this view", () => {
    FakeMap.instances.length = 0;
    const view = makeView("slot:map");
    const { store } = renderPanel(view);
    const map = FakeMap.instances.at(-1)!;
    act(() => {
      store.getState().handle({
        type: "ui",
        action: "fly_to",
        payload: { lng: 5, lat: 6, zoom: 9 },
        target: view.id,
      });
    });
    expect(map.flyToCalls).toEqual([{ center: [5, 6], zoom: 9 }]);
  });

  it("ignores a fly_to action targeted at a different view", () => {
    FakeMap.instances.length = 0;
    const view = makeView("slot:map");
    const { store } = renderPanel(view);
    const map = FakeMap.instances.at(-1)!;
    act(() => {
      store.getState().handle({
        type: "ui",
        action: "fly_to",
        payload: { lng: 5, lat: 6 },
        target: "slot:other",
      });
    });
    expect(map.flyToCalls).toEqual([]);
  });

  it("removes the map on unmount", () => {
    FakeMap.instances.length = 0;
    const { unmount } = renderPanel(makeView("slot:map"));
    const map = FakeMap.instances.at(-1)!;
    unmount();
    expect(map.removed).toBe(true);
  });
});
