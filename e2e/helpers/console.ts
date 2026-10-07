import type { Page } from "@playwright/test";

export interface ConsoleTracker {
  /** Console errors and uncaught exceptions seen so far, one line each. */
  errors(): string[];
}

export interface TrackOptions {
  /**
   * Logged-out pages ask GET /api/auth/me and get the documented 401. Chrome
   * logs every non-2xx fetch as "Failed to load resource" at error level and
   * the page cannot suppress that, so it is ignored for this one URL only.
   */
  allowAnonymousMe?: boolean;
}

function isAnonymousMe(text: string, url: string): boolean {
  return /status of 401/.test(text) && /\/api\/auth\/me(\?|$)/.test(url);
}

/** Starts recording console errors and page errors; call before navigating. */
export function trackConsoleErrors(page: Page, options: TrackOptions = {}): ConsoleTracker {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    const url = message.location().url;
    if (options.allowAnonymousMe && isAnonymousMe(message.text(), url)) return;
    errors.push(`console.error: ${message.text()}${url ? ` (${url})` : ""}`);
  });
  page.on("pageerror", (error) => {
    errors.push(`pageerror: ${error.name}: ${error.message}`);
  });
  return { errors: () => [...errors] };
}
