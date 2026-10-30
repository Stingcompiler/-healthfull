import { Link, Outlet, useRouterState } from "@tanstack/react-router";
import { LogOut } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { BrandMark } from "@/components/BrandMark";
import { CenterIdentity } from "@/components/CenterIdentity";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { ThemeSwitcher } from "@/components/ThemeSwitcher";
import { Button } from "@/components/ui/button";
import { getSiteConfig, signInPath } from "@/lib/site";
import { cn } from "@/lib/utils";

import { usePortalMe } from "./api";
import { CenterFooter } from "./components/CenterFooter";
import { NoticesBell } from "./components/NoticesBell";
import { sitePage } from "./lib/center-tasks";
import { useSignOut } from "./lib/session";

/**
 * The web manifest and theme colour of the portal, added while a portal screen is open (the
 * staff app has none). No service worker: medical data is never cached for offline use.
 */
function usePortalManifest() {
  useEffect(() => {
    const link = document.createElement("link");
    link.rel = "manifest";
    link.href = "/portal.webmanifest";
    document.head.appendChild(link);
    return () => {
      link.remove();
    };
  }, []);
}

/**
 * Patient portal shell: mobile-first, single column, no staff navigation.
 * Same SPA and server as the staff app (ARCHITECTURE 1, src/portal). The center website at `/`
 * (ADR 0028 decision 4) renders it with the center page as `children` instead of the outlet.
 */
export function PortalLayout({ children }: { children?: ReactNode } = {}) {
  const { t } = useTranslation("portal");
  const me = usePortalMe();
  const signOut = useSignOut();
  const [leaving, setLeaving] = useState(false);
  usePortalManifest();
  const signedIn = Boolean(me.data);
  const path = useRouterState({ select: (st) => st.location.pathname });
  // Signed out, the one action (sign in) stays reachable in the sticky header while the
  // visitor scrolls the center page (LANDING section 2); the sign-in page needs no copy.
  // Patient sign-in switched off (ADR 0029): no sign-in action anywhere on the public pages.
  const site = getSiteConfig();
  const tracking = site.patientTracking;
  const showSignIn = tracking && !signedIn && !path.startsWith("/portal/sign-in");
  // The public website (the center page and the two guest booking pages, D-0022, D-0023) is wide
  // (two columns from lg) with the website's header and footer; every other portal screen stays a
  // phone-width column. The center page's hero carries the center's name, so the header keeps
  // only the compact portal brand, and on phones its sticky bottom bar replaces the header button.
  const pageKind = sitePage(path);
  const isCenter = pageKind === "center";
  const isSite = pageKind !== null;
  const width = isSite ? "max-w-[75rem] md:px-6 lg:px-8" : "max-w-md md:max-w-2xl";

  return (
    <div className="flex min-h-dvh flex-col bg-bg" data-density="comfortable">
      <header className="site-glass sticky top-0 z-20 border-b border-border print:hidden">
        <div className={cn("mx-auto flex h-14 w-full items-center justify-between gap-2 px-4", width)}>
          <Link
            to={signedIn ? "/portal/home" : "/portal"}
            className="flex min-h-11 min-w-0 items-center gap-2 rounded-control focus-ring"
          >
            {isSite ? (
              <span className="flex min-w-0 items-center gap-2.5" data-testid="portal-brand">
                <BrandMark className="size-8" />
                <span className="truncate text-sm font-bold text-fg">{t("brand")}</span>
              </span>
            ) : (
              <CenterIdentity subtitle={t("brand")} />
            )}
          </Link>
          <div className="flex shrink-0 items-center">
            {showSignIn ? (
              <Button
                asChild
                size="sm"
                variant={isCenter ? "default" : "soft"}
                className={cn("me-1", isCenter && "max-md:hidden")}
              >
                <Link to="/portal/sign-in" data-testid="portal-header-sign-in">
                  {t("center.signInShort")}
                </Link>
              </Button>
            ) : null}
            {signedIn ? <NoticesBell /> : null}
            <LanguageSwitcher />
            <ThemeSwitcher labelled />
            {signedIn ? (
              <Button
                variant="ghost"
                size="icon"
                aria-label={t("nav.signOut")}
                title={t("nav.signOut")}
                loading={leaving}
                data-testid="portal-sign-out"
                onClick={() => {
                  setLeaving(true);
                  void signOut("signed-out").finally(() => {
                    setLeaving(false);
                  });
                }}
              >
                <LogOut aria-hidden="true" className="rtl:-scale-x-100" />
              </Button>
            ) : null}
          </div>
        </div>
      </header>
      <main
        id="main"
        className={cn("mx-auto w-full flex-1 px-4 py-6 print:max-w-none print:p-0", width, isSite && "lg:py-8")}
      >
        {children ?? <Outlet />}
      </main>
      {isSite && site.centerSite ? (
        // The center website's own footer (D-0022): contact, hours, links and the vendor line. The
        // guest pages' phone action bar sits in the page's flow (sticky), so it needs no room here.
        <CenterFooter reserveBar={isCenter ? undefined : false} />
      ) : (
        <footer
          // The fixed phone tab bar (signed in) sits over the page's end: leave its height plus the
          // device's safe area free, so the last card is never under it. (`safe-bottom` alone set
          // padding-bottom to the inset and cancelled the tab-bar room.)
          className={cn(
            "mx-auto w-full px-4 text-center text-xs text-muted print:hidden",
            width,
            signedIn
              ? "pb-[calc(6rem+env(safe-area-inset-bottom))] md:pb-6"
              : "pb-[calc(1.5rem+env(safe-area-inset-bottom))]",
          )}
        >
          <p>{t("privacy")}</p>
          {signedIn ? null : (
            <Link
              to={signInPath()}
              className="mt-1 inline-flex min-h-11 items-center px-2 font-medium text-primary-strong underline-offset-4 hover:underline"
            >
              {t("staffLink")}
            </Link>
          )}
        </footer>
      )}
    </div>
  );
}
