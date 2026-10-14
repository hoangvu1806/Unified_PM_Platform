import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, "..", "");
  const port = Number(env.FRONTEND_PORT);
  if (!Number.isInteger(port) || port <= 0) throw new Error("FRONTEND_PORT is required");
  return {
    envDir: "..",
    plugins: [react()],
    server: {
      host: "127.0.0.1",
      port,
      proxy: {
        "/api": {
          target: "http://127.0.0.1:8282",
          changeOrigin: true,
        },
      },
    },
  };
});
