import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the API, media and share pages come from the Python server (python -m yatta.app).
const backend = "http://127.0.0.1:8790";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": backend, "/media": backend, "/watch": backend },
  },
  build: { outDir: "dist", sourcemap: true },
});
