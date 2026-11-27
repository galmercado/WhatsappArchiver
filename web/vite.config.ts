import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Dev: run the API with WA_BASE_URL=http://localhost:5173 so Origin/CSRF checks line up.
const api = "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", sourcemap: false, target: "es2022" },
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: { "/api": api, "/auth": api, "/vault": api, "/healthz": api },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    globalSetup: ["./src/test/tz.ts"],
    css: false,
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
