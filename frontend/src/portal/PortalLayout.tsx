import { Link, Outlet } from "@tanstack/react-router";
import { LogOut } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { BrandMark } from "@/components/BrandMark";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { ThemeSwitcher } from "@/components/ThemeSwitcher";
import { Button } from "@/components/ui/button";

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

  return (
    <div className="flex min-h-dvh flex-col bg-bg">
      <header className="sticky top-0 z-20 border-b border-border bg-surface/90 backdrop-blur print:hidden">
        <div className="mx-auto flex h-14 w-full max-w-md items-center justify-between gap-2 px-4 md:max-w-2xl">
          <Link
            to={signedIn ? "/portal/home" : "/portal"}
            className="flex min-h-11 min-w-0 items-center gap-2 rounded-control focus-ring"
          >
            <BrandMark className="size-8" />
            <span className="truncate text-sm font-bold text-fg">{t("brand")}</span>
          </Link>
          <div className="flex items-center">
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
        className={`mx-auto w-full max-w-md px-4 safe-bottom text-center text-xs text-muted md:max-w-2xl print:hidden ${
          signedIn ? "pb-24 md:pb-6" : "pb-6"
        }`}
      >
        <p>{t("privacy")}</p>
        {signedIn ? null : (
          <Link
            to="/login"
            className="mt-1 inline-flex min-h-11 items-center px-2 font-medium text-primary-strong underline-offset-4 hover:underline"
          >
            {t("staffLink")}
          </Link>
        )}
      </footer>
    </div>
  );
}
