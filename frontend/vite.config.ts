import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

import { API_PROXY_TARGET, rewriteApiPath } from "./dev-proxy";

/**
 * Vite config.
 *
 * ## The `/api` prefix is ours, not the backend's
 *
 * The backend mounts its routers at the **root** (`app.include_router(ads_router)`,
 * with no `prefix=`), so the real endpoints are `GET /ads` and `GET /competitors`.
 *
 * The client speaks to `/api/ads` and `/api/competitors` instead. Two reasons:
 *
 * 1. A same-origin `/api/...` path is indistinguishable from the app's own routes and
 *    asset requests, so the dev proxy can route on it without ambiguity.
 * 2. In production the prefix is what a reverse proxy or CDN can route on.
 *
 * Because the backend has no prefix, the proxy has to **strip** ours. Without the
 * `rewrite` below, `/api/ads` arrives at the backend as `/api/ads` and 404s -- which
 * reads exactly like "the API is down" and is not.
 *
 * ## No CORS, on purpose
 *
 * The backend has no CORS middleware. A dev proxy means the browser only ever makes
 * same-origin requests, so none is needed and none was added to `backend/` (S3.3 must
 * not modify backend code).
 */
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: API_PROXY_TARGET,
        changeOrigin: true,
        rewrite: rewriteApiPath,
      },
    },
  },
  build: {
    outDir: "dist",
    // Fail the build rather than silently shipping a bundle that references an
    // asset that 404s. Cheap, and it fails at build time where it is cheap.
    sourcemap: true,
  },
  test: {
    environment: "jsdom",
    globals: true,
    /*
     * One file at a time, in band. This repo runs tests one at a time on purpose, and
     * Vitest 4 dropped `poolOptions.forks.singleFork` in favour of this flag.
     *
     * `threads`, not `forks`: the project path contains a space
     * (`C:\Users\DELL\Downloads\Meta Audit`), and the forks pool spawns a child
     * process whose module path arrives percent-encoded. The worker then never
     * responds and the run fails with "Timeout waiting for worker to respond" -- an
     * error that looks nothing like its cause. Threads share this process, so there
     * is no spawn and no path to mis-encode.
     */
    pool: "threads",
    fileParallelism: false,
    maxWorkers: 1,
    setupFiles: ["./src/test-setup.ts"],
  },
});