import { Link, Outlet } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { BrandMark } from "@/components/BrandMark";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { ThemeSwitcher } from "@/components/ThemeSwitcher";

/**
 * Patient portal shell: mobile-first, single column, no staff navigation.
 * Same SPA and server as the staff app (ARCHITECTURE 1, src/portal).
 */
export function PortalLayout() {
  const { t } = useTranslation("portal");
  return (
    <div className="flex min-h-dvh flex-col bg-bg">
      <header className="sticky top-0 z-10 border-b border-border bg-surface/90 backdrop-blur">
        <div className="mx-auto flex h-14 w-full max-w-md items-center justify-between gap-2 px-4">
          <Link
            to="/portal"
            className="flex min-w-0 items-center gap-2 rounded-control focus-visible:ring-3 focus-visible:ring-ring/35 focus-visible:outline-none"
          >
            <BrandMark className="size-8" />
            <span className="truncate text-sm font-bold text-fg">{t("brand")}</span>
          </Link>
          <div className="flex items-center">
            <LanguageSwitcher variant="icon" />
            <ThemeSwitcher />
          </div>
        </div>
      </header>
      <main id="main" className="mx-auto w-full max-w-md flex-1 px-4 py-6">
        <Outlet />
      </main>
      <footer className="mx-auto w-full max-w-md px-4 pb-6 safe-bottom text-center text-xs text-muted">
        <p>{t("privacy")}</p>
        <Link
          to="/login"
          className="mt-2 inline-block font-medium text-primary-strong underline-offset-4 hover:underline"
        >
          {t("staffLink")}
        </Link>
      </footer>
    </div>
  );
}
