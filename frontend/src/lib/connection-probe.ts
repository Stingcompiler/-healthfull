/** Public, unauthenticated, cheap: the same endpoint the update script uses. */
export const HEALTH_PATH = "/api/ops/health";
export const PROBE_TIMEOUT_MS = 4_000;

/** Whether the server answered a health probe with success. Never throws. */
export async function probeServer(fetcher: typeof fetch = fetch): Promise<boolean> {
  try {
    const response = await fetcher(HEALTH_PATH, {
      cache: "no-store",
      credentials: "same-origin",
      signal: AbortSignal.timeout(PROBE_TIMEOUT_MS),
    });
    return response.ok;
  } catch {
    return false;
  }
}
