import { fileURLToPath, URL } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  // shadcn/ui convention (components.json): "@/components/ui/button" is src/components/ui/button.
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    proxy: {
      "/api": process.env.ADM_API_URL ?? "http://localhost:8010"
    }
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/testSetup.ts"]
  }
});
