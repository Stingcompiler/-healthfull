import { Link, useNavigate, useRouterState } from "@tanstack/react-router";
import { Banknote, CalendarClock, FileStack, Scale, type LucideIcon } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";

type ClaimsPath = "/claims" | "/claims/batches" | "/claims/payments" | "/claims/aging";

interface ClaimsLink {
  to: ClaimsPath;
  key: "receivables" | "claims" | "payments" | "aging";
  icon: LucideIcon;
}

/** The claims module's screens; every one needs `claims.view` (the nav entry's permission). */
const CLAIMS_LINKS: readonly ClaimsLink[] = [
  { to: "/claims", key: "receivables", icon: Scale },
  { to: "/claims/batches", key: "claims", icon: FileStack },
  { to: "/claims/payments", key: "payments", icon: Banknote },
  { to: "/claims/aging", key: "aging", icon: CalendarClock },
];

/** The tab a path belongs to: a claim, its print view and the batch builder belong to Claims. */
function activePath(pathname: string): ClaimsPath | undefined {
  const path = pathname.replace(/\/+$/, "") || "/";
  const exact = CLAIMS_LINKS.find((l) => l.to === path);
  if (exact) return exact.to;
  if (path.startsWith("/claims/")) return "/claims/batches";
  return undefined;
}

/**
 * Sub-navigation shared by every claims screen. From md up: a row of pills; on phones one
 * select naming the current screen, so the work is not pushed below the fold.
 */
export function ClaimsNav() {
  const { t } = useTranslation("claims");
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const current = activePath(pathname);

  return (
    <nav aria-label={t("nav.label")} data-slot="claims-nav" className="print:hidden">
      <div className="md:hidden">
        <Select
          value={current ?? ""}
          onValueChange={(to) => {
            void navigate({ to });
          }}
        >
          <SelectTrigger className="h-11 w-full" aria-label={t("nav.label")} data-testid="claims-nav-select">
            <SelectValue placeholder={t("nav.label")} />
          </SelectTrigger>
          <SelectContent>
            {CLAIMS_LINKS.map((link) => {
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
        {CLAIMS_LINKS.map((link) => {
          const Icon = link.icon;
          const active = current === link.to;
          return (
            <li key={link.to}>
              <Link
                to={link.to}
                data-testid={`claims-nav-${link.key}`}
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
