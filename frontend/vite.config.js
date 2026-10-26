import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  base: "/static/react/",
  build: { outDir: "../rezak/static/react", emptyOutDir: true },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8765",
      "^/static/(?!react/)": "http://127.0.0.1:8765",
    },
  },
});
