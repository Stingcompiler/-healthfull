import { Link, Outlet, useNavigate, useRouterState } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useCurrentUser } from "@/lib/auth/hooks";
import { hasPermission } from "@/lib/auth/permissions";
import { cn } from "@/lib/utils";

import { ADMIN_SECTIONS } from "../sections";

/**
 * Shell of every administration page: the sub-navigation (a side list from lg,
 * a section picker below it) beside the page. The index page (section cards)
 * has no sub-navigation.
 */
export function AdminLayout() {
  const { t } = useTranslation(["admin", "nav"]);
  const me = useCurrentUser();
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (s) => s.location.pathname.replace(/\/$/, "") });
  const sections = ADMIN_SECTIONS.filter((s) => hasPermission(me, s.permission));
  const current = ADMIN_SECTIONS.find((s) => pathname === s.to || pathname.startsWith(`${s.to}/`));

  if (pathname === "/administration" || !current) return <Outlet />;

  return (
    <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:gap-6">
      <nav aria-label={t("admin:subnav")} className="lg:sticky lg:top-4 lg:w-56 lg:shrink-0">
        <div className="lg:hidden">
          <Select
            value={current.id}
            onValueChange={(id) => {
              const target = sections.find((s) => s.id === id);
              if (target) void navigate({ to: target.to });
            }}
          >
            <SelectTrigger aria-label={t("admin:subnav")} className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(sections.includes(current) ? sections : [current, ...sections]).map((s) => (
                <SelectItem key={s.id} value={s.id}>
                  {t(`nav:items.${s.navKey}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <ul className="hidden flex-col gap-0.5 lg:flex">
          <li>
            <Link
              to="/administration"
              className="mb-2 block rounded-control px-3 py-2 text-xs font-semibold tracking-wide text-muted uppercase focus-ring hover:text-fg"
            >
              {t("admin:title")}
            </Link>
          </li>
          {sections.map((s) => {
            const Icon = s.icon;
            const active = s.id === current.id;
            return (
              <li key={s.id}>
                <Link
                  to={s.to}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "flex items-center gap-2.5 rounded-control px-3 py-2 text-sm focus-ring transition-colors",
                    active
                      ? "bg-primary-soft font-semibold text-primary-strong"
                      : "text-fg-muted hover:bg-accent hover:text-fg",
                  )}
                >
                  <Icon className="size-4 shrink-0" aria-hidden="true" />
                  <span className="truncate">{t(`nav:items.${s.navKey}`)}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
      <div className="min-w-0 flex-1">
        <Outlet />
      </div>
    </div>
  );
}
