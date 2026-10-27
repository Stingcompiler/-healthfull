/**
 * Deployment switches the server publishes before sign-in (ADR 0027): is `/login` the product
 * page, and how can a visitor of that page reach the vendor. Read once at start from
 * `GET /api/ops/site`, so one build serves every deployment and nothing is rebuilt per install.
 *
 * Off (the default, and the answer when the server cannot be reached) keeps `/login` the plain
 * staff sign-in. `/sign-in` always shows the staff sign-in too. Every redirect that sends a
 * visitor to sign in goes through `signInPath()`.
 */

export interface SiteConfig {
  marketing: boolean;
  contactEmail: string | null;
  contactWhatsapp: string | null;
}

const OFF: SiteConfig = { marketing: false, contactEmail: null, contactWhatsapp: null };

let current: SiteConfig = OFF;

export function getSiteConfig(): SiteConfig {
  return current;
}

/** Tests and `loadSiteConfig` only. */
export function setSiteConfig(next: Partial<SiteConfig> | null): void {
  current = next ? { ...OFF, ...next } : OFF;
}

export function isMarketingSite(): boolean {
  return current.marketing;
}

/** Where a signed-out visitor goes to sign in: `/sign-in` when `/login` is the product page. */
export function signInPath(): "/login" | "/sign-in" {
  return current.marketing ? "/sign-in" : "/login";
}

/** True for both addresses of the staff sign-in page. */
export function isSignInPath(pathname: string): boolean {
  return pathname === "/login" || pathname === "/sign-in";
}

const SITE_TIMEOUT_MS = 3_000;

/**
 * Fetches the switches. Never throws and never waits long: a server that does not answer
 * leaves the marketing page off, which is the safe state (a plain sign-in always works).
 */
export async function loadSiteConfig(fetcher: typeof fetch = fetch): Promise<SiteConfig> {
  try {
    const response = await fetcher("/api/ops/site", {
      cache: "no-store",
      credentials: "same-origin",
      signal: AbortSignal.timeout(SITE_TIMEOUT_MS),
    });
    if (!response.ok) {
      setSiteConfig(null);
      return OFF;
    }
    const body = (await response.json()) as Record<string, unknown>;
    setSiteConfig({
      marketing: body.marketing === true,
      contactEmail: typeof body.contact_email === "string" ? body.contact_email : null,
      contactWhatsapp: typeof body.contact_whatsapp === "string" ? body.contact_whatsapp : null,
    });
  } catch {
    setSiteConfig(null);
  }
  return current;
}
