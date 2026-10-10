import { useQueryClient } from "@tanstack/react-query";
import { Link, Outlet, useRouterState } from "@tanstack/react-router";
import { CalendarDays, FlaskConical, House, Pill, ReceiptText, type LucideIcon } from "lucide-react";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";

import type { AppPath } from "@/app/nav-types";
import { isApiError } from "@/lib/api/errors";
import { cn } from "@/lib/utils";

import { usePortalMe } from "./api";
import { useSignOut } from "./lib/session";

interface PortalNavItem {
  id: "home" | "appointments" | "results" | "prescriptions" | "bills";
  to: AppPath;
  icon: LucideIcon;
  /** Other paths that belong to this section. */
  also?: string[];
}

const NAV: readonly PortalNavItem[] = [
  { id: "home", to: "/portal/home", icon: House },
  { id: "appointments", to: "/portal/appointments", icon: CalendarDays },
  { id: "results", to: "/portal/results", icon: FlaskConical },
  { id: "prescriptions", to: "/portal/prescriptions", icon: Pill },
  { id: "bills", to: "/portal/invoices", icon: ReceiptText, also: ["/portal/receipts"] },
];

function PortalNav() {
  const { t } = useTranslation("portal");
  const path = useRouterState({ select: (s) => s.location.pathname });
  return (
    <nav
      aria-label={t("nav.label")}
      data-slot="portal-nav"
      className={cn(
        "z-20 border-border bg-surface/95 backdrop-blur print:hidden",
        // Phones: a tab bar at the bottom; from md: a row under the header.
        "fixed inset-x-0 bottom-0 border-t safe-bottom md:static md:mb-5 md:rounded-card md:border",
      )}
    >
      <ul className="mx-auto grid max-w-md grid-cols-5 md:max-w-none">
        {NAV.map(({ id, to, icon: Icon, also }) => {
          const active = path === to || path.startsWith(`${to}/`) || (also ?? []).some((p) => path.startsWith(p));
          return (
            <li key={id} className="min-w-0">
              <Link
                to={to}
                data-testid={`portal-nav-${id}`}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex min-h-14 flex-col items-center justify-center gap-0.5 px-1 text-[11px] focus-ring-inset md:min-h-11 md:flex-row md:gap-2 md:text-sm",
                  active ? "font-semibold text-primary-strong" : "text-muted hover:text-fg",
                )}
              >
                <Icon className="size-5 shrink-0 md:size-4" aria-hidden="true" />
                <span className="max-w-full truncate">{t(`nav.${id}`)}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

/**
 * Screens of a signed-in patient. The session idles out on the server; here the screen also
 * signs out after the same idle time (a shared phone or a clinic tablet), and any portal call
 * answered 401 (session ended elsewhere) returns to the sign-in page.
 */
export function PortalAuthedLayout() {
  const me = usePortalMe();
  const queryClient = useQueryClient();
  const signOut = useSignOut();
  const idleSeconds = me.data?.idle_seconds ?? 0;

  useEffect(() => {
    const onPortal401 = (error: unknown, meta: Record<string, unknown> | undefined) => {
      if (meta?.portal && isApiError(error) && error.status === 401) void signOut("expired");
    };
    const unsubscribeQueries = queryClient.getQueryCache().subscribe((event) => {
      if (event.type === "updated" && event.action.type === "error") onPortal401(event.action.error, event.query.meta);
    });
    const unsubscribeMutations = queryClient.getMutationCache().subscribe((event) => {
      if (event.type === "updated" && event.action.type === "error") {
        onPortal401(event.action.error, event.mutation.meta);
      }
    });
    return () => {
      unsubscribeQueries();
      unsubscribeMutations();
    };
  }, [queryClient, signOut]);

  useEffect(() => {
    if (idleSeconds <= 0) return undefined;
    let timer = window.setTimeout(expire, idleSeconds * 1000);
    function expire() {
      void signOut("expired");
    }
    const reset = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(expire, idleSeconds * 1000);
    };
    const events = ["pointerdown", "keydown", "scroll", "touchstart"] as const;
    for (const name of events) window.addEventListener(name, reset, { passive: true });
    return () => {
      window.clearTimeout(timer);
      for (const name of events) window.removeEventListener(name, reset);
    };
  }, [idleSeconds, signOut]);

  return (
    <>
      <PortalNav />
      <Outlet />
    </>
  );
}
