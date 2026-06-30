// The canvas renderer registry: the extension seam. A pinned view has a `kind`
// ("plot", "report", "image", …); the canvas looks up a panel component for that
// kind and mounts it. Built-in kinds render in an <iframe> (live/HTML views) or an
// <img> (static images, and a resumed plot's poster). An extension adds a new
// surface — e.g. a MapLibre map to place geothermal wells — by calling
// `registerPanel("map", MapPanel)`; no change to the canvas core is needed.

import { useEffect, useRef, useState } from "react";

import { useSel } from "../context";
import type { UiAction, View } from "../store";

export interface PanelProps {
  view: View;
  active: boolean;
  /** Changes when the view should reload (a same-slot refresh, or "back"). */
  reloadToken: number;
  /** Call when the panel's content has finished loading (clears the spinner). */
  onLoaded: () => void;
  /** Send a payload back to the agent as a `ui_event` (e.g. a map click). */
  onUiEvent: (payload: unknown) => void;
  /** Trigger a direct, non-LLM action (see ActionHandler) — e.g. the map's
   *  "Setup Simulation"/"Run" buttons, which have nothing for the model to
   *  decide and so bypass it entirely rather than going through `onUiEvent`. */
  onAction: (name: string, args?: Record<string, unknown>) => void;
}

/** A panel's own hook for reading the `ui` actions the agent has targeted at
 *  it (see protocol.ts's `ui.target`) — call with the panel's own `view.id`.
 *  Each batch is delivered exactly once: reading it drains the store's queue. */
export function useUiActions(viewId: string): UiAction[] {
  const queued = useSel((s) => s.uiActions[viewId]);
  const consumeUiActions = useSel((s) => s.consumeUiActions);
  const [drained, setDrained] = useState<UiAction[]>([]);
  useEffect(() => {
    if (queued && queued.length) setDrained(consumeUiActions(viewId));
  }, [queued, consumeUiActions, viewId]);
  return drained;
}

export type Panel = (props: PanelProps) => React.ReactElement;

const registry: Record<string, Panel> = {};

export function registerPanel(kind: string, panel: Panel): void {
  registry[kind] = panel;
}

// Each mounted IframePanel's actual DOM node, keyed by view id — a host app
// embedding e.g. a map needs to postMessage into its iframe's contentWindow,
// which the view's plain data object (no DOM ref) can't give it.
const frames = new Map<string, HTMLIFrameElement>();

export function getFrame(id: string): HTMLIFrameElement | undefined {
  return frames.get(id);
}

/** Toggle pointer-events on every mounted iframe: while dragging the canvas
 *  resize grip, an iframe'd view (a plot, report, or an embedded map) would
 *  otherwise swallow mousemove the instant the cursor crosses into it — it's a
 *  separate browsing context, so those events never reach the window's own
 *  listener. Disabling pointer events for the drag's duration keeps the
 *  cursor's moves landing on the window throughout. */
export function setAllFramesInert(inert: boolean): void {
  for (const frame of frames.values()) frame.style.pointerEvents = inert ? "none" : "";
}

/** A view renders as an image when it is a true image OR its URL points at one —
 *  on resume a live plot falls back to its PNG poster, which must not sit in an
 *  iframe (that shows the browser's bare, mis-sized image viewer). */
export function isImageView(view: View): boolean {
  return view.kind === "image" || /\.(png|jpe?g|gif|svg|webp|bmp)(?:[?#]|$)/i.test(view.url || "");
}

function withToken(url: string, token: number): string {
  if (token <= 0) return url;
  return url + (url.includes("?") ? "&" : "?") + "_=" + token;
}

export function ImagePanel({ view, active, reloadToken, onLoaded }: PanelProps) {
  return (
    <img
      className={active ? "active" : ""}
      src={withToken(view.url, reloadToken)}
      alt={view.title}
      onLoad={onLoaded}
      onError={onLoaded}
    />
  );
}

export function IframePanel({ view, active, reloadToken, onLoaded }: PanelProps) {
  // A live WebGL figure reflows once right after `load` (WGLMakie sizes to its
  // parent only after mounting), so clearing the loader on `load` would flash a
  // mis-sized first frame; hold briefly for plots. Reports don't reflow.
  const hold = view.kind === "plot" ? 450 : 0;
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  // Clear a pending hold-timer if the panel unmounts first (tab/canvas closed),
  // so a stale onLoaded can't fire against a view that is already gone.
  useEffect(() => () => clearTimeout(timer.current), []);
  const handleLoad = () => {
    if (hold) timer.current = setTimeout(onLoaded, hold);
    else onLoaded();
  };
  return (
    <iframe
      ref={(node) => {
        if (node) frames.set(view.id, node);
        else frames.delete(view.id);
      }}
      className={active ? "active" : ""}
      title={view.title}
      loading="lazy"
      src={withToken(view.url, reloadToken)}
      onLoad={handleLoad}
      onError={onLoaded}
    />
  );
}

export function panelFor(view: View): Panel {
  if (isImageView(view)) return ImagePanel;
  return registry[view.kind] ?? IframePanel;
}

/** A view can be meaningfully opened in a new browser tab when it renders
 *  from a real URL — an image, or an iframe'd page (any kind not in the
 *  native-panel registry). A view backed by a registered native panel (e.g.
 *  the map) renders live React/component state the URL never reflects: its
 *  `view.url` is a stub artifact kept only to satisfy the artifact-pin wire
 *  contract, so opening it just shows an empty page. */
export function hasOpenableUrl(view: View): boolean {
  return isImageView(view) || !(view.kind in registry);
}
