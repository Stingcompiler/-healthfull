import { Link, useNavigate, useRouterState } from "@tanstack/react-router";
import {
  ClipboardCheck,
  Clock3,
  FileMinus,
  Landmark,
  ScanLine,
  ShieldCheck,
  Undo2,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useCurrentUser } from "@/lib/auth/hooks";
import { hasPermission } from "@/lib/auth/permissions";
import { cn } from "@/lib/utils";

type CashierPath =
  | "/cashier"
  | "/cashier/shift"
  | "/cashier/transfers"
  | "/cashier/credit-notes"
  | "/cashier/refunds"
  | "/cashier/perform-first"
  | "/cashier/review"
  | "/cashier/receipt-check";

interface CashierLink {
  to: CashierPath;
  key: "workspace" | "shift" | "transfers" | "creditNotes" | "refunds" | "performFirst" | "review" | "receiptCheck";
  icon: LucideIcon;
  permission: string | readonly string[];
}

/** The cashier module's screens; each shows only to users who may use it (UI hint only). */
const CASHIER_LINKS: readonly CashierLink[] = [
  { to: "/cashier", key: "workspace", icon: Wallet, permission: ["billing.view", "payments.view"] },
  { to: "/cashier/shift", key: "shift", icon: Clock3, permission: "payments.open_shift" },
  { to: "/cashier/transfers", key: "transfers", icon: Landmark, permission: "payments.confirm_transfer" },
  { to: "/cashier/credit-notes", key: "creditNotes", icon: FileMinus, permission: "billing.view" },
  { to: "/cashier/refunds", key: "refunds", icon: Undo2, permission: "payments.view" },
  {
    to: "/cashier/perform-first",
    key: "performFirst",
    icon: ShieldCheck,
    permission: "orders.authorize_perform_first",
  },
  { to: "/cashier/review", key: "review", icon: ClipboardCheck, permission: "payments.review_shift" },
  { to: "/cashier/receipt-check", key: "receiptCheck", icon: ScanLine, permission: "payments.view" },
];

/**
 * The tab a path belongs to. Exact matches only, so `/cashier/shifts/12` (any cashier's shift,
 * opened from Shift review) never lights up "My shift"; printed documents belong to the desk.
 */
function activeCashierPath(pathname: string): CashierPath | undefined {
  const path = pathname.replace(/\/+$/, "") || "/";
  if (path === "/cashier" || path.startsWith("/cashier/receipts/") || path.startsWith("/cashier/invoices/")) {
    return "/cashier";
  }
  if (path.startsWith("/cashier/shifts/")) return "/cashier/review";
  return CASHIER_LINKS.find((l) => l.to === path)?.to;
}

/**
 * Sub-navigation shared by every cashier screen. From md up: a row of pills (wrapping). On
 * phones: one select naming the current screen, so the work is not pushed below the fold.
 */
export function CashierNav() {
  const { t } = useTranslation("cashier");
  const me = useCurrentUser();
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const current = activeCashierPath(pathname);
  const links = CASHIER_LINKS.filter((l) => hasPermission(me, l.permission, "any"));
  if (links.length === 0) return null;

  return (
    <nav aria-label={t("nav.label")} data-slot="cashier-nav" className="print:hidden">
      <div className="md:hidden">
        <Select
          value={current ?? ""}
          onValueChange={(to) => {
            void navigate({ to });
          }}
        >
          <SelectTrigger className="h-11 w-full" aria-label={t("nav.label")} data-testid="cashier-nav-select">
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
                data-testid={`cashier-nav-${link.key}`}
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
