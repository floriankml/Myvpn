import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Im Entwicklungsmodus werden /api-Aufrufe an das lokale Backend weitergeleitet.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8080" } },
  build: { sourcemap: false, target: "es2022" },
});
