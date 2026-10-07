/**
 * Where the e2e run lives: repo paths, worktree hash, ports, database name and
 * base URL. scripts/e2e.sh computes and exports the same values (it also picks
 * free ports when the defaults are busy); the fallbacks here let
 * `pnpm test` run on its own with the formulas from ARCHITECTURE section 3:
 *
 *   hash          = first 8 hex chars of sha1(<physical repo root path>)
 *   BACKEND_PORT  = 20000 + int(hash, 16) % 20000
 *   FRONTEND_PORT = BACKEND_PORT + 1
 *   E2E_DB_NAME   = e2e_hospital_<hash>
 */
import { createHash } from "node:crypto";
import { realpathSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

export const E2E_DIR = here;
export const REPO_ROOT = realpathSync(path.resolve(here, ".."));
export const BACKEND_DIR = path.join(REPO_ROOT, "backend");
export const FRONTEND_DIR = path.join(REPO_ROOT, "frontend");
export const SCREENS_DIR = path.join(REPO_ROOT, "artifacts", "screens");
export const LOGS_DIR = path.join(here, ".logs");
export const AUTH_DIR = path.join(here, ".auth");

export const REPO_HASH = createHash("sha1").update(REPO_ROOT).digest("hex").slice(0, 8);

function port(name: string, fallback: number): number {
  const raw = process.env[name];
  if (raw === undefined || raw === "") return fallback;
  const value = Number.parseInt(raw, 10);
  if (!Number.isInteger(value) || value < 1 || value > 65535) {
    throw new Error(`${name} must be a TCP port (1..65535), got "${raw}"`);
  }
  return value;
}

export const BACKEND_PORT = port("BACKEND_PORT", 20000 + (Number.parseInt(REPO_HASH, 16) % 20000));
export const FRONTEND_PORT = port("FRONTEND_PORT", BACKEND_PORT + 1);
/**
 * The e2e database. Read from E2E_DB_NAME (exported by scripts/e2e.sh), never from DB_NAME:
 * a shell that exported DB_NAME=hospital_dev for `make dev` must not get seed_e2e (which resets
 * accounts to known test passwords) or the lockout specs run against the dev database.
 */
export const DB_NAME = e2eDatabaseName(process.env.E2E_DB_NAME);

export function e2eDatabaseName(raw: string | undefined): string {
  const name = raw === undefined || raw === "" ? `e2e_hospital_${REPO_HASH}` : raw;
  if (!/^e2e_hospital_[a-z0-9_]+$/.test(name)) {
    throw new Error(`E2E_DB_NAME must look like e2e_hospital_<id>, got "${name}"`);
  }
  return name;
}

/** The SPA origin. The API is reached through Vite's proxy on the same origin. */
export const BASE_URL = `http://127.0.0.1:${String(FRONTEND_PORT)}`;
export const BACKEND_URL = `http://127.0.0.1:${String(BACKEND_PORT)}`;

/** Hosts the app may talk to. Anything else is an internet dependency (offline.spec). */
export const LOCAL_HOSTNAMES: ReadonlySet<string> = new Set(["127.0.0.1", "localhost", "[::1]", "::1"]);
