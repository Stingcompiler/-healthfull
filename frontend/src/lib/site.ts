/**
 * Deployment switches the server publishes before sign-in, read once at start from
 * `GET /api/ops/site`, so one build serves every deployment and nothing is rebuilt per install:
 *
 * - the vendor's marketing page (ADR 0027): is `/login` the product page, and how a visitor of
 *   that page reaches the vendor;
 * - the center administrator's switches (ADR 0028, 0029): the center website (`centerSite`,
 *   shown at `/` and `/portal`), online booking and patient sign-in. The server enforces them;
 *   here they only choose what to show.
 *
 * Off (the default, and the answer when the server cannot be reached) keeps `/login` the plain
 * staff sign-in and every public page closed. `/sign-in` always shows the staff sign-in too.
 * Every redirect that sends a visitor to sign in goes through `signInPath()`.
 */

export interface SiteConfig {
  marketing: boolean;
  contactEmail: string | null;
  contactWhatsapp: string | null;
  centerSite: boolean;
  onlineBooking: boolean;
  patientTracking: boolean;
}

const OFF: SiteConfig = {
  marketing: false,
  contactEmail: null,
  contactWhatsapp: null,
  centerSite: false,
  onlineBooking: false,
  patientTracking: false,
};

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

/**
 * What the exact path `/` shows a visitor without a staff session (ADR 0028 decision 4): the
 * center website wins over the vendor sales page; with neither, the staff sign-in (`null`).
 */
export function rootPublicView(config: SiteConfig = current): "center" | "marketing" | null {
  if (config.centerSite) return "center";
  if (config.marketing) return "marketing";
  return null;
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
 * leaves every switch off, which is the safe state (a plain sign-in always works).
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
      centerSite: body.center_site === true,
      onlineBooking: body.online_booking === true,
      patientTracking: body.patient_tracking === true,
    });
  } catch {
    setSiteConfig(null);
  }
  return current;
}
