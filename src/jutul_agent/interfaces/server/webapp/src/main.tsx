import { createRoot } from "react-dom/client";
import { App } from "./App";
import { MapPanel } from "./canvas/MapPanel";
import { registerPanel } from "./canvas/registry";
import "./styles/index.css";

// The built-in "map" panel — see docs/web-ui.md's "Extending the canvas".
registerPanel("map", MapPanel);

// No <StrictMode>: the session holds one imperative WebSocket, and StrictMode's
// dev-only double-mount would open it twice. The shipped production build never
// double-mounts; correctness is covered by the store's unit tests instead.
const root = document.getElementById("root");
if (root) createRoot(root).render(<App />);
