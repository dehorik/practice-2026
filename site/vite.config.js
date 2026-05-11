import { resolve } from "node:path";
import { defineConfig } from "vite";

export default defineConfig({
  server: {
    allowedHosts: [".ngrok-free.dev", ".ngrok-free.app"]
  },
  build: {
    rollupOptions: {
      input: {
        main: resolve(__dirname, "index.html"),
        about: resolve(__dirname, "about.html"),
        participants: resolve(__dirname, "participants.html"),
        journal: resolve(__dirname, "journal.html"),
        resources: resolve(__dirname, "resources.html"),
        variant: resolve(__dirname, "variant.html")
      }
    }
  }
});
