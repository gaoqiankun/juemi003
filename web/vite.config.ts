import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const devApiTarget = process.env.GEN3D_DEV_API_TARGET || "http://127.0.0.1:19001";

export default defineConfig({
  base: "/static/",
  plugins: [react()],
  server: {
    proxy: {
      "/health": devApiTarget,
      "/ready": devApiTarget,
      "/readiness": devApiTarget,
      "/metrics": devApiTarget,
      "/docs": devApiTarget,
      "/redoc": devApiTarget,
      "/openapi.json": devApiTarget,
      "/v1": devApiTarget,
      "/admin": devApiTarget,
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
