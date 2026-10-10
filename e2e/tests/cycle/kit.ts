/**
 * Shared steps of the cycle specs (Phase 8 hardening):
 *
 * - `Watch`: every browser context of the full-cycle spec is opened through it, so every request
 *   to a host other than this machine is recorded AND aborted (as in offline.spec.ts), and every
 *   console error or uncaught page error is collected for one assertion at the end;
 * - English pages per seed user, a phone page for the patient portal;
 * - `Backend`: a second Django server spawned by the restart spec on its own port (never the
 *   Playwright-managed one), hard-killed and started again, with a small CSRF-aware API client.
 */
import { spawn, type ChildProcess } from "node:child_process";
import { closeSync, openSync } from "node:fs";
import { createServer } from "node:net";
import path from "node:path";

import {
  expect,
  request,
  type APIRequestContext,
  type Browser,
  type BrowserContext,
  type Page,
} from "@playwright/test";

import { BACKEND_DIR, DB_NAME, LOCAL_HOSTNAMES, LOGS_DIR } from "../../env";
import type { SeedUser } from "../../fixtures/users";
import { apiLogin, login, setPrefs, tr, trackConsoleErrors, type ConsoleTracker } from "../../helpers";

export const LANG = "en" as const;

export function t(key: string, vars: Record<string, string> = {}): string {
  return tr(LANG, key, vars);
}

/** "3780.00" as the en screens print it ("3,780.00"), sign optional. */
export function sdg(amount: string): RegExp {
  const [int = "0", frac = "00"] = amount.replace(/^-/, "").split(".");
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return new RegExp(`${grouped}\\.${frac}`);
}

/** A unique run suffix of letters only (names refuse digits), e.g. "Kqzrt". */
export function letters(n = 5): string {
  const abc = "abcdefghijklmnopqrstuvwxyz";
  let out = "";
  for (let i = 0; i < n; i += 1) out += abc[Math.floor(Math.random() * abc.length)];
  return out.charAt(0).toUpperCase() + out.slice(1);
}

/** A Sudanese mobile number nobody else in the shared database has. */
export function uniquePhone(): string {
  return `09${String(Date.now()).slice(-8)}`;
}

/** Picks an option of a shared Select by its accessible label. */
export async function choose(page: Page, label: string, option: string | RegExp): Promise<void> {
  await page.getByRole("combobox", { name: label }).click();
  await page.getByRole("option", { name: option }).first().click();
}

// ------------------------------------------------------------------------------------------------
// Offline watch: no request may leave this machine, no console error may go unnoticed
// ------------------------------------------------------------------------------------------------

export function isExternal(raw: string): boolean {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return false;
  }
  if (!["http:", "https:", "ws:", "wss:"].includes(url.protocol)) return false; // data:, blob:, about:
  return !LOCAL_HOSTNAMES.has(url.hostname);
}

export interface WatchOptions {
  /** Console lines that are a documented answer of this flow, never a failure (kept narrow). */
  allowConsole?: readonly RegExp[];
}

export class Watch {
  /** "<METHOD> <url>" of every request to a non-local host (all aborted). */
  readonly external: string[] = [];
  private readonly trackers: { label: string; tracker: ConsoleTracker }[] = [];
  private readonly contexts: BrowserContext[] = [];

  constructor(
    private readonly browser: Browser,
    private readonly options: WatchOptions = {},
  ) {}

  /** A new browser context with the offline guard; window.print is a no-op. */
  async context(viewport: { width: number; height: number }): Promise<BrowserContext> {
    const context = await this.browser.newContext({ viewport, acceptDownloads: true });
    this.contexts.push(context);
    context.on("request", (req) => {
      if (isExternal(req.url())) this.external.push(`${req.method()} ${req.url()}`);
    });
    await context.route(
      (url) => isExternal(url.href),
      (route) => route.abort("internetdisconnected"),
    );
    await context.addInitScript(() => {
      window.print = () => undefined;
    });
    return context;
  }

  private async page(context: BrowserContext, label: string): Promise<Page> {
    const page = await context.newPage();
    page.on("websocket", (socket) => {
      if (isExternal(socket.url())) this.external.push(`WS ${socket.url()}`);
    });
    this.trackers.push({ label, tracker: trackConsoleErrors(page, { allowAnonymousMe: true }) });
    return page;
  }

  /** A staff member signed in through the login screen, English, light theme. */
  async staff(who: SeedUser, width = 1280): Promise<Page> {
    const context = await this.context({ width, height: 900 });
    const page = await this.page(context, who);
    await login(page, who);
    await setPrefs(page, { theme: "light", lang: LANG });
    return page;
  }

  /** A patient's phone: no staff session, English, light theme. */
  async phone(width = 375): Promise<Page> {
    const context = await this.context({ width, height: 812 });
    const page = await this.page(context, "portal");
    await setPrefs(page, { theme: "light", lang: LANG });
    return page;
  }

  /** Console errors and page errors of every page so far, minus the allowed lines. */
  errors(): string[] {
    const allowed = this.options.allowConsole ?? [];
    return this.trackers.flatMap(({ label, tracker }) =>
      tracker
        .errors()
        .filter((line) => !allowed.some((re) => re.test(line)))
        .map((line) => `[${label}] ${line}`),
    );
  }

  async close(): Promise<void> {
    for (const context of this.contexts.splice(0)) await context.close().catch(() => undefined);
  }
}

/** Waits for the JSON answer of the API call that `action` triggers (method + path pattern). */
export async function answerOf<T>(
  page: Page,
  method: string,
  pathPattern: RegExp,
  action: () => Promise<void>,
): Promise<T> {
  const waiting = page.waitForResponse(
    (r) => r.request().method() === method && pathPattern.test(new URL(r.url()).pathname),
  );
  await action();
  const response = await waiting;
  expect(response.status(), `${method} ${response.url()}: ${await response.text()}`).toBeLessThan(300);
  return (await response.json()) as T;
}

// ------------------------------------------------------------------------------------------------
// A second backend for the restart spec
// ------------------------------------------------------------------------------------------------

/** A TCP port nothing listens on right now (the OS picks it). */
export function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.unref();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      if (address === null || typeof address === "string") {
        server.close();
        reject(new Error("no port"));
        return;
      }
      const { port } = address;
      server.close(() => resolve(port));
    });
  });
}

async function listening(url: string): Promise<boolean> {
  try {
    const response = await fetch(url, { signal: AbortSignal.timeout(2_000) });
    return response.status === 200;
  } catch {
    return false;
  }
}

/**
 * Django `runserver --noreload` on 127.0.0.1:<port> against the e2e database, with the
 * environment playwright.config.ts gives the shared backend (DB_NAME, DJANGO_DEBUG=1). It runs
 * in its own process group so a hard kill takes `uv` and the Python child together.
 */
export class Backend {
  private child: ChildProcess | null = null;
  private exited: Promise<void> = Promise.resolve();
  readonly url: string;
  starts = 0;

  constructor(readonly port: number) {
    this.url = `http://127.0.0.1:${String(port)}`;
  }

  async start(): Promise<void> {
    if (this.child) throw new Error("backend already running");
    if (await listening(`${this.url}/api/ops/health`)) throw new Error(`port ${String(this.port)} is taken`);
    const log = openSync(path.join(LOGS_DIR, `restart-backend-${String(this.port)}.log`), "a");
    const child = spawn(
      "uv",
      ["run", "python", "manage.py", "runserver", `127.0.0.1:${String(this.port)}`, "--noreload"],
      {
        cwd: BACKEND_DIR,
        env: {
          ...process.env,
          DB_NAME,
          BACKEND_PORT: String(this.port),
          DJANGO_DEBUG: "1",
        },
        detached: true,
        stdio: ["ignore", log, log],
      },
    );
    closeSync(log);
    this.child = child;
    this.starts += 1;
    this.exited = new Promise((resolve) => {
      child.once("exit", () => resolve());
    });
    const deadline = Date.now() + 90_000;
    while (!(await listening(`${this.url}/api/ops/health`))) {
      if (child.exitCode !== null) throw new Error(`backend exited with ${String(child.exitCode)} (see ${LOGS_DIR})`);
      if (Date.now() > deadline) throw new Error(`backend on ${this.url} did not answer /api/ops/health`);
      await new Promise((r) => setTimeout(r, 250));
    }
  }

  /** SIGKILL to the whole process group: no shutdown hook, no flush, like a power cut. */
  async kill(): Promise<void> {
    const child = this.child;
    if (!child?.pid) return;
    this.child = null;
    try {
      process.kill(-child.pid, "SIGKILL");
    } catch {
      // already gone
    }
    await this.exited;
    const deadline = Date.now() + 15_000;
    while (await listening(`${this.url}/api/ops/health`)) {
      if (Date.now() > deadline) throw new Error(`port ${String(this.port)} still answers after SIGKILL`);
      await new Promise((r) => setTimeout(r, 100));
    }
  }

  get running(): boolean {
    return this.child !== null;
  }
}

/** A non-2xx answer of the spawned backend. */
export class ServerError extends Error {
  constructor(
    readonly status: number,
    readonly body: { code?: string; message?: string } | null,
    what: string,
  ) {
    super(`${what} -> ${String(status)}: ${JSON.stringify(body)}`);
  }

  get code(): string | undefined {
    return this.body?.code;
  }
}

/** A seed user's session on the spawned backend (session + csrftoken cookies, X-CSRFToken). */
export class ServerApi {
  private constructor(
    readonly who: SeedUser,
    readonly context: APIRequestContext,
  ) {}

  static async login(baseURL: string, who: SeedUser): Promise<ServerApi> {
    const context = await request.newContext({ baseURL, storageState: { cookies: [], origins: [] } });
    await apiLogin(context, who);
    return new ServerApi(who, context);
  }

  private async csrf(): Promise<string> {
    const token = (await this.context.storageState()).cookies.find((c) => c.name === "csrftoken")?.value;
    if (!token) throw new Error("no csrftoken cookie");
    return token;
  }

  async send<T>(
    method: "GET" | "POST",
    url: string,
    data?: unknown,
    timeout = 30_000,
  ): Promise<{ status: number; body: T }> {
    const headers: Record<string, string> = method === "GET" ? {} : { "X-CSRFToken": await this.csrf() };
    const response = await this.context.fetch(url, { method, headers, data, timeout });
    const text = await response.text();
    return { status: response.status(), body: (text ? JSON.parse(text) : null) as T };
  }

  async get<T>(url: string): Promise<T> {
    const { status, body } = await this.send<T>("GET", url);
    if (status >= 300) throw new ServerError(status, body as never, `GET ${url}`);
    return body;
  }

  async post<T>(url: string, data: unknown): Promise<T> {
    const { status, body } = await this.send<T>("POST", url, data);
    if (status >= 300) throw new ServerError(status, body as never, `POST ${url}`);
    return body;
  }

  dispose(): Promise<void> {
    return this.context.dispose();
  }
}
