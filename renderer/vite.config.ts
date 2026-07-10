import { defineConfig } from "vite";

// Vite dev server + build for the PixiJS renderer. The dev port matches the
// docker-compose `renderer` service (BRIEF §6). Tests run under vitest with
// globals enabled so specs read `describe/it/expect` without imports.
export default defineConfig({
  server: {
    port: 5173,
    host: true,
  },
  test: {
    globals: true,
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
