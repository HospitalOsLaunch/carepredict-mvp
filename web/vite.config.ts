/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { viteSingleFile } from "vite-plugin-singlefile";

// "demo" mode produces one self-contained HTML file running on bundled fixtures,
// suitable for sharing a preview. The default build talks to the local API.
export default defineConfig(({ mode }) => ({
  plugins: mode === "demo" ? [react(), viteSingleFile()] : [react()],
  define: { __DEMO_ONLY__: JSON.stringify(mode === "demo") },
  build: { outDir: mode === "demo" ? "dist-demo" : "dist" },
  server: {
    port: 5173,
    proxy: {
      // Platform gateway (src/hospitalos/platform): accounts, settings, journal, and the authenticated
      // routes to the hybrid engine (:8000) and the 24-hour planner (:8765). Same paths as production.
      "/api": { target: "http://127.0.0.1:8100" },
    },
  },
  test: { environment: "jsdom", globals: true },
}));
