import { Outlet, useLocation, useNavigate } from "@tanstack/react-router";
import { Loader2 } from "lucide-react";
import { useEffect, useMemo, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { safeRedirectTarget } from "@/app/guards";
import { visibleNav } from "@/app/nav";
import { AppShell } from "@/components/AppShell";
import { ConnectionBanner } from "@/components/ConnectionBanner";
import { NotificationBell } from "@/features/notifications/NotificationBell";
import { usePatientQuickSearch } from "@/features/patients/quick-search";
import { useMe } from "@/lib/auth/hooks";
import { useSessionState } from "@/lib/auth/session";
import { isSignInPath, signInPath } from "@/lib/site";
import { ConnectionProvider } from "@/lib/hooks/use-server-connection";
import { densityAttribute, densityForPath } from "@/lib/density";

import { ReauthDialog } from "./ReauthDialog";

/**
 * Keeps the authenticated area consistent after the initial route guard: a user who is not
 * signed in is sent to /login with a way back, and a forced password change always comes first.
 *
 * When the session ends while a page is open (expiry, sign-out elsewhere: any 401 under a
 * signed-in user), the page is NOT unmounted: it is hidden (state, drafts and the page's own
 * leave guard stay in memory) and `ReauthDialog` asks for the password (inspection F06). The
 * page's wrapper is the same element in every state, so hiding it never remounts it.
 */
export function AuthGuard({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const { data: me, isPending } = useMe();
  const session = useSessionState();
  const navigate = useNavigate();
  const pathname = useLocation({ select: (l) => l.pathname });
  const href = useLocation({ select: (l) => l.href });

  useEffect(() => {
    // An ended session is handled by the dialog, never by a redirect.
    if (isPending || session !== null) return;
    // The router's location changes as soon as a navigation starts, while this
    // layout is still mounted. Once we are on the way to /login or
    // /change-password (our own redirect, or the user menu's logout) there is
    // nothing left to do; redirecting again would nest ?redirect=/login?...
    // forever and React would abort with "Maximum update depth exceeded".
    if (!me) {
      if (isSignInPath(pathname)) return;
      void navigate({ to: signInPath(), search: { redirect: safeRedirectTarget(href) ?? undefined }, replace: true });
    } else if (me.must_change_password) {
      if (pathname === "/change-password") return;
      void navigate({ to: "/change-password", replace: true });
    }
  }, [me, isPending, session, navigate, pathname, href]);

  const expired = session?.kind === "expired" ? session : null;
  if (session?.kind === "switching" || !me || (me.must_change_password && !expired)) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-bg" role="status">
        <Loader2 className="size-6 animate-spin text-primary" aria-hidden="true" />
        <span className="sr-only">{t("loading")}</span>
        {expired ? <ReauthDialog session={expired} /> : null}
      </div>
    );
  }
  return (
    <>
      <div
        className={expired ? "hidden" : "contents"}
        inert={expired ? true : undefined}
        aria-hidden={expired ? true : undefined}
        data-testid="auth-guarded"
      >
        {children}
      </div>
      {expired ? <ReauthDialog session={expired} /> : null}
    </>
  );
}

export function AppLayout() {
  const { data: me } = useMe();
  const nav = useMemo(() => visibleNav(me ?? null), [me]);
  const quickSearch = usePatientQuickSearch();
  const density = densityAttribute(densityForPath(useLocation({ select: (l) => l.pathname })));
  return (
    <AuthGuard>
      <ConnectionProvider>
        <AppShell nav={nav} quickSearch={quickSearch} actions={<NotificationBell />}>
          {/* display: contents keeps the layout as it was; only the density tokens are scoped here. */}
          <div data-density={density} className="contents">
            <ConnectionBanner />
            <Outlet />
          </div>
        </AppShell>
      </ConnectionProvider>
    </AuthGuard>
  );
}
