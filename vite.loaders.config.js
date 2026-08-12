import { resolve } from "node:path";
import { defineConfig } from "vite";

export default defineConfig({
  define: {
    "process.env.NODE_ENV": JSON.stringify("production"),
  },
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
      entry: resolve(import.meta.dirname, "frontend/generative-loaders.jsx"),
      name: "GenerativeLoadersRuntime",
      formats: ["iife"],
      fileName: () => "generative-loaders.js",
      cssFileName: "generative-loaders",
    },
  },
});
