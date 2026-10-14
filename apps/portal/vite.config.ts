import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Served at / by the platform gateway. Dev server proxies the core API.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api/core": "http://localhost:8080" } },
});
