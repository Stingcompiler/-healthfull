import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { searchForWorkspaceRoot, type ProxyOptions } from "vite";
import { configDefaults, defineConfig } from "vitest/config";

// Ports always come from the environment (ARCHITECTURE section 3): several
// worktrees may run side by side, so nothing here is hardcoded beyond defaults.
function envPort(name: string, fallback: number): number {
  const raw = process.env[name];
  if (raw === undefined || raw === "") return fallback;
  const port = Number.parseInt(raw, 10);
  if (!Number.isInteger(port) || port <= 0 || port > 65535) {
    throw new Error(`${name} must be a valid TCP port, got "${raw}"`);
  }
  return port;
}

const frontendPort = envPort("FRONTEND_PORT", 5173);
const backendPort = envPort("BACKEND_PORT", 8000);
const backendTarget = `http://127.0.0.1:${String(backendPort)}`;

// changeOrigin stays false on purpose: Django then sees the same Host as the
// browser's Origin, so CSRF origin checks pass and the session/csrftoken
// cookies are host-only cookies for 127.0.0.1, shared by the SPA and the API.
const backendProxy: ProxyOptions = {
  target: backendTarget,
  changeOrigin: false,
  xfwd: true,
};

// Keys starting with "^" are regular expressions. They match whole path
// segments so SPA routes such as /administration are NOT sent to Django
// (a plain "/admin" key would prefix-match them).
const proxy: Record<string, ProxyOptions> = {
  "^/api(/|$)": backendProxy,
  "^/admin(/|$)": backendProxy,
  // Django admin assets, only relevant when /admin is opened through Vite.
  "^/static/": backendProxy,
};

// Vitest only: src/lib/api/error-codes.test.ts reads the backend sources (?raw) to check
// that every API error code is translated. The dev server keeps Vite's default file
// access (this package only), so it never serves backend files.
const testFsAllow = process.env.VITEST
  ? { fs: { allow: [searchForWorkspaceRoot(process.cwd()), fileURLToPath(new URL("../backend", import.meta.url))] } }
  : {};

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    host: "127.0.0.1",
    port: frontendPort,
    strictPort: true,
    proxy,
    ...testFsAllow,
  },
  preview: {
    host: "127.0.0.1",
    port: frontendPort,
    strictPort: true,
    proxy,
  },
  build: {
    target: "es2022",
    sourcemap: true,
    chunkSizeWarningLimit: 1500,
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    // Only tokens.css is read in tests (as ?raw, by the contrast test).
    css: { include: [/tokens\.css/] },
    restoreMocks: true,
    exclude: [...configDefaults.exclude, "e2e/**"],
  },
});
