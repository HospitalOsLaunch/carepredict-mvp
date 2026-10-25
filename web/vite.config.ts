/// <reference types="vitest" />
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import { viteSingleFile } from "vite-plugin-singlefile";

// "demo" mode produces one self-contained HTML file running on bundled fixtures,
// suitable for sharing a preview. The default build talks to the local API.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "HOSPITALOS_DEMO_");
  const apiPort = Number(env.HOSPITALOS_DEMO_API_PORT ?? "8000");
  if (!Number.isInteger(apiPort) || apiPort < 1 || apiPort > 65535) {
    throw new Error("HOSPITALOS_DEMO_API_PORT must be a valid local port");
  }
  return {
    plugins: mode === "demo" ? [react(), viteSingleFile()] : [react()],
    define: { __DEMO_ONLY__: JSON.stringify(mode === "demo") },
    build: { outDir: mode === "demo" ? "dist-demo" : "dist" },
    server: {
      port: 5173,
      proxy: {
        // Hybrid observation API or explicit simulator gateway, loopback only.
        "/api": { target: `http://127.0.0.1:${apiPort}`, rewrite: (p) => p.replace(/^\/api/, "") },
      },
    },
    test: { environment: "jsdom", globals: true },
  };
});
