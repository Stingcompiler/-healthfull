import { Outlet, useLocation, useNavigate } from "@tanstack/react-router";
import { Loader2 } from "lucide-react";
import { useEffect, useMemo, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { safeRedirectTarget } from "@/app/guards";
import { visibleNav } from "@/app/nav";
import { AppShell } from "@/components/AppShell";
import { NotificationBell } from "@/features/notifications/NotificationBell";
import { usePatientQuickSearch } from "@/features/patients/quick-search";
import { useMe } from "@/lib/auth/hooks";

/**
 * Keeps the authenticated area consistent after the initial route guard:
 * if the session ends (logout elsewhere, expiry, any 401) the user is sent
 * to /login with a way back; a forced password change always comes first.
 */
export function AuthGuard({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const { data: me, isPending } = useMe();
  const navigate = useNavigate();
  const pathname = useLocation({ select: (l) => l.pathname });
  const href = useLocation({ select: (l) => l.href });

  useEffect(() => {
    if (isPending) return;
    // The router's location changes as soon as a navigation starts, while this
    // layout is still mounted. Once we are on the way to /login or
    // /change-password (our own redirect, or the user menu's logout) there is
    // nothing left to do; redirecting again would nest ?redirect=/login?...
    // forever and React would abort with "Maximum update depth exceeded".
    if (!me) {
      if (pathname === "/login") return;
      void navigate({ to: "/login", search: { redirect: safeRedirectTarget(href) ?? undefined }, replace: true });
    } else if (me.must_change_password) {
      if (pathname === "/change-password") return;
      void navigate({ to: "/change-password", replace: true });
    }
  }, [me, isPending, navigate, pathname, href]);

  if (!me || me.must_change_password) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-bg" role="status">
        <Loader2 className="size-6 animate-spin text-primary" aria-hidden="true" />
        <span className="sr-only">{t("loading")}</span>
      </div>
    );
  }
  return children;
}

export function AppLayout() {
  const { data: me } = useMe();
  const nav = useMemo(() => visibleNav(me ?? null), [me]);
  const quickSearch = usePatientQuickSearch();
  return (
    <AuthGuard>
      <AppShell nav={nav} quickSearch={quickSearch} actions={<NotificationBell />}>
        <Outlet />
      </AppShell>
    </AuthGuard>
  );
}
