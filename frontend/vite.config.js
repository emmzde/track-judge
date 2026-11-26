import { defineConfig } from "vite";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [
    tailwindcss(),
    {
      name: "desktop-client-directive",
      // The complete bundle runs in WebView2. Hoist React's client boundary to its entry.
      transform: {
        filter: {
          id: /node_modules[\\/](?:@radix-ui|lucide-react)[\\/]/,
          code: /["']use client["']/,
        },
        handler(code) {
          return code.replace(/^\s*["']use client["'];?/m, "");
        },
      },
    },
  ],
  build: {
    outDir: "../src/trackjudge/desktop/static",
    emptyOutDir: true,
    license: { fileName: "licenses.md" },
    rolldownOptions: { output: { banner: '"use client";' } },
  },
});
