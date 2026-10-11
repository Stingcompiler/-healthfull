import { Link, useNavigate, useRouterState } from "@tanstack/react-router";
import {
  ArrowLeftRight,
  CalendarClock,
  ClipboardList,
  Package,
  Pill,
  ShoppingBag,
  SlidersHorizontal,
  TrendingDown,
  Truck,
  Undo2,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useCurrentUser } from "@/lib/auth/hooks";
import { hasPermission } from "@/lib/auth/permissions";
import { cn } from "@/lib/utils";

type PharmacyPath =
  | "/pharmacy"
  | "/pharmacy/sale"
  | "/pharmacy/items"
  | "/pharmacy/receipts"
  | "/pharmacy/adjustments"
  | "/pharmacy/counts"
  | "/pharmacy/transfers"
  | "/pharmacy/expiry"
  | "/pharmacy/low-stock"
  | "/pharmacy/returns";

type LinkKey =
  | "dispense"
  | "returns"
  | "sale"
  | "items"
  | "receipts"
  | "adjustments"
  | "counts"
  | "transfers"
  | "expiry"
  | "lowStock";

interface PharmacyLink {
  to: PharmacyPath;
  key: LinkKey;
  icon: LucideIcon;
  permission: string | readonly string[];
}

/** The pharmacy module's screens; each shows only to users who may use it (UI hint only). */
const PHARMACY_LINKS: readonly PharmacyLink[] = [
  { to: "/pharmacy", key: "dispense", icon: Pill, permission: "pharmacy.dispense" },
  { to: "/pharmacy/returns", key: "returns", icon: Undo2, permission: "pharmacy.dispense" },
  { to: "/pharmacy/sale", key: "sale", icon: ShoppingBag, permission: "billing.pharmacy_sale" },
  { to: "/pharmacy/items", key: "items", icon: Package, permission: "pharmacy.view" },
  { to: "/pharmacy/receipts", key: "receipts", icon: Truck, permission: "pharmacy.view" },
  { to: "/pharmacy/adjustments", key: "adjustments", icon: SlidersHorizontal, permission: "pharmacy.view" },
  { to: "/pharmacy/counts", key: "counts", icon: ClipboardList, permission: "pharmacy.view" },
  { to: "/pharmacy/transfers", key: "transfers", icon: ArrowLeftRight, permission: "pharmacy.view" },
  { to: "/pharmacy/expiry", key: "expiry", icon: CalendarClock, permission: "pharmacy.view" },
  { to: "/pharmacy/low-stock", key: "lowStock", icon: TrendingDown, permission: "pharmacy.view" },
];

/** The tab a path belongs to: an item's page belongs to Items, a count sheet to Counts. */
function activePharmacyPath(pathname: string): PharmacyPath | undefined {
  const path = pathname.replace(/\/+$/, "") || "/";
  if (path.startsWith("/pharmacy/items/")) return "/pharmacy/items";
  if (path.startsWith("/pharmacy/counts/")) return "/pharmacy/counts";
  return PHARMACY_LINKS.find((l) => l.to === path)?.to;
}

/**
 * Sub-navigation shared by every pharmacy screen. From md up: a row of pills (wrapping). On
 * phones: one select naming the current screen, so the work is not pushed below the fold.
 */
export function PharmacyNav() {
  const { t } = useTranslation("pharmacy");
  const me = useCurrentUser();
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const current = activePharmacyPath(pathname);
  const links = PHARMACY_LINKS.filter((l) => hasPermission(me, l.permission, "any"));
  if (links.length <= 1) return null;

  return (
    <nav aria-label={t("nav.label")} data-slot="pharmacy-nav" className="print:hidden">
      <div className="md:hidden">
        <Select
          value={current ?? ""}
          onValueChange={(to) => {
            void navigate({ to });
          }}
        >
          <SelectTrigger className="h-11 w-full" aria-label={t("nav.label")} data-testid="pharmacy-nav-select">
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
                data-testid={`pharmacy-nav-${link.key}`}
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
