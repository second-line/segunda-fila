import { defineConfig } from "astro/config";
import sitemap from "@astrojs/sitemap";

export default defineConfig({
  site: "https://segunda-fila.pages.dev",
  integrations: [
    sitemap()
  ]
});
