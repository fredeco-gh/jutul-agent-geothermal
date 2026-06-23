// The canvas: the persistent right-side panel of pinned views. All views stay
// mounted (visibility toggled by the `.active` class) so switching tabs preserves
// each frame's state. Panels come from the canvas registry, so new view kinds plug
// in without touching this component.

import { useState } from "react";

import { isImageView, panelFor } from "../canvas/registry";
import { useSel } from "../context";
import { BackIcon, CloseIcon, KindIcon, PopoutIcon } from "../icons";

export function Canvas() {
  const views = useSel((s) => s.views);
  const viewOrder = useSel((s) => s.viewOrder);
  const activeView = useSel((s) => s.activeView);
  const canvasOpen = useSel((s) => s.canvasOpen);
  const openView = useSel((s) => s.openView);
  const removeView = useSel((s) => s.removeView);
  const closeCanvas = useSel((s) => s.closeCanvas);

  // Per-(view, reload) "has loaded" set drives the spinner; a new reload token is
  // automatically "not loaded" until its panel fires onLoaded.
  const [loaded, setLoaded] = useState<ReadonlySet<string>>(() => new Set());
  const [backBump, setBackBump] = useState<Record<string, number>>({});

  const tokenOf = (id: string) => (views[id]?.nonce ?? 0) + (backBump[id] ?? 0);
  const loadKey = (id: string) => `${id}@${tokenOf(id)}`;
  const markLoaded = (id: string, token: number) =>
    setLoaded((prev) => new Set(prev).add(`${id}@${token}`));

  const active = activeView ? views[activeView] : null;
  const showLoading = !!active && !loaded.has(loadKey(active.id));

  const onResizeStart = (e: React.MouseEvent) => {
    e.preventDefault();
    document.body.style.userSelect = "none";
    const move = (ev: MouseEvent) => {
      // Store the width as a fraction of the viewport, so the split stays
      // proportional across window resizes and screen changes.
      const frac = Math.min(Math.max((window.innerWidth - ev.clientX) / window.innerWidth, 0.3), 0.62);
      document.documentElement.style.setProperty("--canvas-w", (frac * 100).toFixed(1) + "%");
    };
    const up = () => {
      document.body.style.userSelect = "";
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  };

  const reloadActive = () => {
    if (!active) return;
    setBackBump((b) => ({ ...b, [active.id]: (b[active.id] ?? 0) + 1 }));
  };

  return (
    <aside className="canvas" hidden={!canvasOpen}>
      <div className="canvas-grip" title="Drag to resize" onMouseDown={onResizeStart} />
      <div className="canvas-head">
        <div className="canvas-tabs">
          {viewOrder.map((id) => {
            const view = views[id];
            if (!view) return null;
            return (
              <button
                key={id}
                className={`tab${id === activeView ? " active" : ""}`}
                onClick={() => openView(id)}
              >
                <span className="tab-ico">
                  <KindIcon kind={view.kind} />
                </span>
                <span className="tab-label">{view.title}</span>
                <span
                  className="tab-close"
                  title="Remove view"
                  onClick={(e) => {
                    e.stopPropagation();
                    removeView(id);
                  }}
                >
                  <CloseIcon />
                </span>
              </button>
            );
          })}
        </div>
        <div className="canvas-actions">
          {active && !isImageView(active) ? (
            <button className="icon-btn" title="Back to this view" onClick={reloadActive}>
              <BackIcon />
            </button>
          ) : null}
          <button
            className="icon-btn"
            title="Open in a new tab"
            onClick={() => active && window.open(active.url, "_blank", "noopener")}
          >
            <PopoutIcon />
          </button>
          <button className="icon-btn" title="Close panel" onClick={closeCanvas}>
            <CloseIcon />
          </button>
        </div>
      </div>
      <div className="canvas-body">
        {viewOrder.map((id) => {
          const view = views[id];
          if (!view) return null;
          const token = tokenOf(id);
          const Panel = panelFor(view);
          return (
            <Panel
              key={id}
              view={view}
              active={id === activeView}
              reloadToken={token}
              onLoaded={() => markLoaded(id, token)}
            />
          );
        })}
        {showLoading ? (
          <div className="canvas-loading on">
            <span className="spinner" />
            <span>Loading view…</span>
          </div>
        ) : null}
      </div>
    </aside>
  );
}
