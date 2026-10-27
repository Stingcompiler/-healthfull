import { Link, Outlet, useRouterState } from "@tanstack/react-router";
import { LogOut } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { CenterIdentity } from "@/components/CenterIdentity";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { ThemeSwitcher } from "@/components/ThemeSwitcher";
import { Button } from "@/components/ui/button";
import { signInPath } from "@/lib/site";
import { cn } from "@/lib/utils";

import { usePortalMe } from "./api";
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
 * Same SPA and server as the staff app (ARCHITECTURE 1, src/portal).
 */
export function PortalLayout() {
  const { t } = useTranslation("portal");
  const me = usePortalMe();
  const signOut = useSignOut();
  const [leaving, setLeaving] = useState(false);
  usePortalManifest();
  const signedIn = Boolean(me.data);
  const path = useRouterState({ select: (st) => st.location.pathname });
  // Signed out, the one action (sign in) stays reachable in the sticky header while the
  // visitor scrolls the center page (LANDING section 2); the sign-in page needs no copy.
  const showSignIn = !signedIn && !path.startsWith("/portal/sign-in");

  return (
    <div className="flex min-h-dvh flex-col bg-bg" data-density="comfortable">
      <header className="sticky top-0 z-20 border-b border-border bg-surface/90 backdrop-blur print:hidden">
        <div className="mx-auto flex h-14 w-full max-w-md items-center justify-between gap-2 px-4 md:max-w-2xl">
          <Link
            to={signedIn ? "/portal/home" : "/portal"}
            className="flex min-h-11 min-w-0 items-center gap-2 rounded-control focus-ring"
          >
            <CenterIdentity subtitle={t("brand")} />
          </Link>
          <div className="flex shrink-0 items-center">
            {showSignIn ? (
              <Button asChild size="sm" variant="soft" className="me-1">
                <Link to="/portal/sign-in" data-testid="portal-header-sign-in">
                  {t("center.signInShort")}
                </Link>
              </Button>
            ) : null}
            <LanguageSwitcher variant="icon" />
            <ThemeSwitcher />
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
      <main id="main" className="mx-auto w-full max-w-md flex-1 px-4 py-6 md:max-w-2xl print:max-w-none print:p-0">
        <Outlet />
      </main>
      <footer
        // The fixed phone tab bar (signed in) sits over the page's end: leave its height plus the
        // device's safe area free, so the last card is never under it. (`safe-bottom` alone set
        // padding-bottom to the inset and cancelled the tab-bar room.)
        className={cn(
          "mx-auto w-full max-w-md px-4 text-center text-xs text-muted md:max-w-2xl print:hidden",
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
    </div>
  );
}
