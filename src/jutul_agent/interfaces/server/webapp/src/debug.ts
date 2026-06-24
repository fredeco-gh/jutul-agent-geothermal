// A small debug bridge on `window.jutulDebug` for the headless screenshot/live
// harnesses: it drives the app through the same store/controller a real WebSocket
// message goes through (inject scripted wire events, open views, inspect state)
// without coupling tests to React internals.

import { getFrame } from "./canvas/registry";
import type { Controller } from "./controller";
import type { ClientMessage, ReplayMessage, ServerMessage } from "./protocol";
import type { SessionStore } from "./store";
import type { StoreApi } from "zustand/vanilla";

export interface JutulDebug {
  handle: (m: ServerMessage) => void;
  addUser: (text: string) => void;
  replay: (messages: ReplayMessage[]) => void;
  openView: (id: string) => void;
  closeCanvas: () => void;
  setMeta: (meta: string) => void;
  // A plain string is typed into the composer as if a user sent it (existing
  // debug/screenshot-harness behavior); a raw ClientMessage goes straight onto
  // the socket — the hook a host app's bridge script uses to relay its own
  // events (a ui_event, or a direct action) to the agent.
  send: (msg: string | ClientMessage) => void;
  runSlash: (text: string) => void;
  state: () => SessionStore;
  // Pins a view (e.g. a host app's embedded page) into the canvas exactly like a
  // server-pushed viz message does — the supported way to add one from outside.
  onViz: (msg: Omit<Extract<ServerMessage, { type: "viz" }>, "type">) => void;
  // The DOM node for a pinned iframe view, by id — for a host app that needs to
  // postMessage into its own embedded page's contentWindow.
  getFrame: (id: string) => HTMLIFrameElement | null;
}

declare global {
  interface Window {
    jutulDebug?: JutulDebug;
    /** Host-app hook: return true from this to consume a `ui` action (e.g. apply
     *  it to the host's own controls) instead of surfacing it as a note. */
    onJutulUi?: (msg: Extract<ServerMessage, { type: "ui" }>) => boolean | void;
  }
}

export function installDebug(store: StoreApi<SessionStore>, controller: Controller): void {
  window.jutulDebug = {
    handle: (m) => store.getState().handle(m),
    addUser: (text) => store.getState().addUser(text),
    replay: (messages) => store.getState().replay(messages),
    openView: (id) => store.getState().openView(id),
    closeCanvas: () => store.getState().closeCanvas(),
    setMeta: (meta) => store.setState({ meta }),
    send: (msg) => {
      if (typeof msg === "string") controller.send(msg);
      else controller.transport.send(msg);
    },
    runSlash: (text) => controller.runSlash(text),
    state: () => store.getState(),
    onViz: (msg) => store.getState().pinView(msg),
    getFrame: (id) => getFrame(id) ?? null,
  };
}
