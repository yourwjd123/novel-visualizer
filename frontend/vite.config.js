import { defineConfig } from "vite";
export default defineConfig({
  base: "./",
  build: {
    outDir: "../novelviz/web",
    emptyOutDir: true,
    chunkSizeWarningLimit: 700,
  },
});
