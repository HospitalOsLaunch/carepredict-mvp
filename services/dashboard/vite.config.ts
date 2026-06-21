import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/predict": "http://localhost:8000",
      "/forecast": "http://localhost:8000",
      "/history": "http://localhost:8000",
      "/simulate": "http://localhost:8000",
      "/actions": "http://localhost:8000",
      "/health": "http://localhost:8000",
      "/ready": "http://localhost:8000",
      "/metrics": "http://localhost:8000"
    }
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/testSetup.ts"]
  }
});
