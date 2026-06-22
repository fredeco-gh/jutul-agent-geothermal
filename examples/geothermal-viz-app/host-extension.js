// Bridges jutul-agent's bundled chat UI to an embedded MapLibre app (geothermal-viz),
// pinned as a canvas view next to the chat. Loaded by index.html as an optional,
// host-app-specific extra (see docs/server-interface.md and app.js's jutulDebug/
// onJutulUi hooks, which this relies on rather than forking the bundled UI).
//
// CONFIGURED_MAP_URL is substituted by serve.py before serving this file, so the
// plain server URL works with no query string — the documented `open
// http://<host>:<port>` flow. Falls back to a ?map_url= query param if this file
// is served unrendered (e.g. read directly, or by a different host script).
(function () {
  "use strict";

  const CONFIGURED_MAP_URL = "%%MAP_URL%%";
  const mapUrl = CONFIGURED_MAP_URL.startsWith("%%")
    ? new URLSearchParams(location.search).get("map_url")
    : CONFIGURED_MAP_URL;
  if (!mapUrl) return;

  const mapOrigin = new URL(mapUrl, location.href).origin;
  const MAP_VIEW_ID = "slot:map";

  // Pin the map as an always-open canvas view, independent of any agent turn —
  // it's an iframe like a plot/report view, just registered directly instead of
  // waiting for a server-pushed `viz` message.
  // The map page can't read its parent's origin across the iframe boundary
  // (document.referrer is unreliable, blocked by some referrer policies/extensions),
  // so it's passed explicitly as a query param the map's bridge script reads.
  function childUrl() {
    const sep = mapUrl.includes("?") ? "&" : "?";
    return mapUrl + sep + "agent_origin=" + encodeURIComponent(location.origin);
  }

  function openMap() {
    if (!window.jutulDebug || !window.jutulDebug.onViz) return;
    // Same path a server-pushed plot/report view takes (updates the tab order
    // too, not just the view registry) — just called directly instead of
    // waiting for a `viz` message, since the map is always open, not tool-gated.
    window.jutulDebug.onViz({ kind: "map", url: childUrl(), title: "Map", slot: "map", silent: true });
    if (reopenBtn) reopenBtn.hidden = true;
  }

  // A small top-right button that appears only once the map tab's own ✕ has
  // fully removed it (closing the canvas panel doesn't — the bundled UI's
  // "Views" button already covers that case). Reopening re-fetches the map
  // fresh, the same way reopening a closed browser tab would.
  let reopenBtn = null;
  function ensureReopenButton() {
    if (reopenBtn) return reopenBtn;
    const actions = document.querySelector(".actions");
    if (!actions) return null;
    reopenBtn = document.createElement("button");
    reopenBtn.className = "ghost";
    reopenBtn.textContent = "Reopen map";
    reopenBtn.hidden = true;
    reopenBtn.onclick = openMap;
    actions.appendChild(reopenBtn);
    return reopenBtn;
  }

  window.onJutulViewClosed = function (id) {
    if (id !== MAP_VIEW_ID) return;
    const btn = ensureReopenButton();
    if (btn) btn.hidden = false;
  };

  // newChat()/resumeSession() wipe every pinned view (resetCanvas), so the map
  // needs to come back on its own each time — switching chats shouldn't require
  // a manual reopen; that button is only for when the user closes it themselves.
  window.onJutulSessionStart = openMap;

  // Outbound: the agent's ui messages are forwarded into the map iframe. This
  // app's ui channel is dedicated to the map, so we suppress the bundled UI's
  // default "gear note" rendering by returning true.
  window.onJutulUi = function (msg) {
    const view = window.jutulDebug.views.get(MAP_VIEW_ID);
    const win = view && view.frame && view.frame.contentWindow;
    if (win) {
      win.postMessage({ type: "ui", action: msg.action, payload: msg.payload }, mapOrigin);
    }
    return true;
  };

  // Inbound: anything the map page posts back becomes a ui_event on the live
  // session socket, exactly like a host app's own interface would emit one.
  window.addEventListener("message", (event) => {
    if (event.origin !== mapOrigin) return;
    window.jutulDebug.send({ type: "ui_event", payload: event.data });
  });

  openMap();
})();
