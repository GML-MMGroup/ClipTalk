import { resolve } from "node:path";
import { defineConfig } from "vite";

export default defineConfig({
  resolve: {
    alias: {
      react: "preact/compat",
      "react-dom": "preact/compat",
      "react-dom/client": "preact/compat/client",
      "react/jsx-runtime": "preact/jsx-runtime",
    },
  },
  build: {
    emptyOutDir: false,
    outDir: resolve(import.meta.dirname, "static"),
    lib: {
      entry: resolve(import.meta.dirname, "frontend/thinking-orbs.jsx"),
      name: "ThinkingOrbsRuntime",
      formats: ["iife"],
      fileName: () => "thinking-orbs.js",
    },
  },
});
