import { Link, useRouterState } from "@tanstack/react-router";
import { ClipboardCheck, Clock3, FileMinus, Landmark, ShieldCheck, Undo2, Wallet, type LucideIcon } from "lucide-react";
import { useTranslation } from "react-i18next";

import { usePermission } from "@/lib/auth/hooks";
import { cn } from "@/lib/utils";

type CashierPath =
  | "/cashier"
  | "/cashier/shift"
  | "/cashier/transfers"
  | "/cashier/credit-notes"
  | "/cashier/refunds"
  | "/cashier/perform-first"
  | "/cashier/review";

interface CashierLink {
  to: CashierPath;
  key: "workspace" | "shift" | "transfers" | "creditNotes" | "refunds" | "performFirst" | "review";
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
];

function NavLink({ link, active }: { link: CashierLink; active: boolean }) {
  const { t } = useTranslation("cashier");
  const allowed = usePermission(link.permission, "any");
  if (!allowed) return null;
  const Icon = link.icon;
  return (
    <li>
      <Link
        to={link.to}
        data-testid={`cashier-nav-${link.key}`}
        aria-current={active ? "page" : undefined}
        className={cn(
          "inline-flex h-11 items-center gap-1.5 rounded-control border px-3 text-sm font-medium whitespace-nowrap focus-ring md:h-9",
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
}

/** Sub-navigation shared by every cashier screen. Wraps on phones (no horizontal scroll). */
export function CashierNav() {
  const { t } = useTranslation("cashier");
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const current = [...CASHIER_LINKS]
    .sort((a, b) => b.to.length - a.to.length)
    .find((l) =>
      l.to === "/cashier" ? pathname === "/cashier" || pathname === "/cashier/" : pathname.startsWith(l.to),
    );
  return (
    <nav aria-label={t("nav.label")} data-slot="cashier-nav" className="print:hidden">
      <ul className="flex flex-wrap gap-2">
        {CASHIER_LINKS.map((link) => (
          <NavLink key={link.to} link={link} active={current?.to === link.to} />
        ))}
      </ul>
    </nav>
  );
}
