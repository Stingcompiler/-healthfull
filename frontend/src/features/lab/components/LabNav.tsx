import { Link, useNavigate, useRouterState } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useCurrentUser } from "@/lib/auth/hooks";
import { hasPermission } from "@/lib/auth/permissions";
import { cn } from "@/lib/utils";

import { activeLabPath, LAB_LINKS } from "../lib/nav";

/**
 * Sub-navigation shared by every lab screen. From md up: a row of pills; on phones one select
 * naming the current screen, so the work is not pushed below the fold.
 */
export function LabNav() {
  const { t } = useTranslation("lab");
  const me = useCurrentUser();
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const current = activeLabPath(pathname);
  const links = LAB_LINKS.filter((l) => hasPermission(me, l.permission));
  if (links.length < 2) return null;

  return (
    <nav aria-label={t("nav.label")} data-slot="lab-nav" className="print:hidden">
      <div className="md:hidden">
        <Select
          value={current ?? ""}
          onValueChange={(to) => {
            void navigate({ to });
          }}
        >
          <SelectTrigger className="h-11 w-full" aria-label={t("nav.label")} data-testid="lab-nav-select">
            <SelectValue placeholder={t("nav.label")} />
          </SelectTrigger>
          <SelectContent>
            {links.map((link) => {
              const Icon = link.icon;
              return (
                <SelectItem key={link.to} value={link.to}>
                  <Icon className="size-4 shrink-0" aria-hidden="true" />
                  {t(`nav.${link.key}`)}
                </SelectItem>
              );
            })}
          </SelectContent>
        </Select>
      </div>
      <ul className="hidden flex-wrap gap-2 md:flex">
        {links.map((link) => {
          const Icon = link.icon;
          const active = current === link.to;
          return (
            <li key={link.to}>
              <Link
                to={link.to}
                data-testid={`lab-nav-${link.key}`}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "inline-flex h-9 items-center gap-1.5 rounded-control border px-3 text-sm font-medium whitespace-nowrap focus-ring",
                  active
                    ? "border-primary bg-primary-soft text-primary-strong"
                    : "border-border bg-surface text-fg-muted hover:bg-accent hover:text-accent-fg",
                )}
              >
                <Icon className="size-4 shrink-0" aria-hidden="true" />
                {t(`nav.${link.key}`)}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
