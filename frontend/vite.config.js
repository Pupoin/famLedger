import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // Prebundle the chart library before serving lazy report routes. Discovering
  // it on the first visit otherwise invalidates already-served dependency URLs.
  optimizeDeps: { include: ["recharts"] },
  server: {
    proxy: {
      "/api": {
        target: process.env.FAMLEDGER_BACKEND_URL || "http://127.0.0.1:8888",
        // Preserve the browser-facing host for the backend's Origin/CSRF check.
        changeOrigin: false,
      },
    },
  },
  test: {
    environment: "node",
  },
});
