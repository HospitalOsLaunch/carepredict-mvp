/// <reference types="vitest" />
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import { viteSingleFile } from "vite-plugin-singlefile";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "HOSPITALOS_");
  const proxy = {
    "/api/decision": {
      target: `http://127.0.0.1:${env.HOSPITALOS_DECISION_PORT || "8765"}`,
      rewrite: (path: string) => path.replace(/^\/api\/decision/, "/api"),
    },
    "/api": {
      target: `http://127.0.0.1:${env.HOSPITALOS_API_PORT || "8000"}`,
      rewrite: (path: string) => path.replace(/^\/api/, ""),
    },
  };
  return {
    plugins: mode === "demo" ? [react(), viteSingleFile()] : [react()],
    define: { __DEMO_ONLY__: JSON.stringify(mode === "demo") },
    build: { outDir: mode === "demo" ? "dist-demo" : "dist" },
    server: { port: 5173, proxy },
    preview: { proxy },
    test: { environment: "jsdom", globals: true },
  };
});
