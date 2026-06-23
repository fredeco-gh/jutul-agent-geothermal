import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// This config is intentionally outside the app's `tsc` scope (tsconfig includes
// only `src`): Vite loads it through esbuild at runtime, so the cross-package
// Vite/Vitest plugin-type friction never blocks the build.
//
// The app is served by FastAPI mounted at "/", from ../web_dist. `base: "./"`
// emits relative asset URLs so the bundle works regardless of the mount path.
export default defineConfig({
  base: "./",
  plugins: [react()],
  build: {
    outDir: "../web_dist",
    emptyOutDir: true,
    chunkSizeWarningLimit: 1500,
  },
  server: {
    // `vite dev` proxies API + WebSocket calls to a locally running FastAPI server
    // so the dev UI drives a real backend. Override the target with JA_DEV_BACKEND.
    proxy: {
      "/sessions": { target: backend(), changeOrigin: true, ws: true },
      "/models": { target: backend(), changeOrigin: true },
      "/simulators": { target: backend(), changeOrigin: true },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    clearMocks: true,
  },
});

function backend(): string {
  return process.env.JA_DEV_BACKEND || "http://127.0.0.1:8181";
}
