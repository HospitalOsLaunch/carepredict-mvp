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
      // FastAPI hybrid app (services/api/hybrid_app.py), loopback only.
      "/api": { target: "http://127.0.0.1:8000", rewrite: (p) => p.replace(/^\/api/, "") },
    },
  },
  test: { environment: "jsdom", globals: true },
}));
