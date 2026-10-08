import { useNavigate, useSearch } from "@tanstack/react-router";
import { MousePointerClick, Wallet } from "lucide-react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { useTranslateError } from "@/lib/api/translate-error";
import { usePermission } from "@/lib/auth/hooks";
import { useShortcut } from "@/lib/hooks/use-shortcut";

import { useCurrentShift, useVisitBilling } from "../api";
import { BillingPanel } from "../components/BillingPanel";
import { CashierNav } from "../components/CashierNav";
import { LOOKUP_INPUT_ID, LOOKUP_SHORTCUT, LookupPanel } from "../components/LookupPanel";
import { PaymentPanel } from "../components/PaymentPanel";
import { ShiftBar } from "../components/ShiftBar";
import { ShortcutsDialog } from "../components/ShortcutsDialog";
import { isPositiveAmount } from "../lib/money";

export interface CashierSearch {
  visit?: number;
  q?: string;
}

export function parseCashierSearch(search: Record<string, unknown>): CashierSearch {
  const visit = Number(search.visit);
  const q = typeof search.q === "string" ? search.q.slice(0, 200) : undefined;
  return {
    ...(Number.isInteger(visit) && visit > 0 ? { visit } : {}),
    ...(q ? { q } : {}),
  };
}

/**
 * The cashier's workspace (FLOW step 4): shift, lookup, billing and payment on one screen,
 * keyboard first (F2 lookup, F4 invoice, F8 approve, F9 amount, Ctrl+Enter pay, ? help).
 */
export function CashierPage() {
  const { t } = useTranslation(["cashier", "errors"]);
  const translateError = useTranslateError();
  const navigate = useNavigate();
  const search = parseCashierSearch(useSearch({ strict: false }));
  const visitId = search.visit;
  const query = search.q ?? "";
  const billing = useVisitBilling(visitId);
  const canShift = usePermission("payments.open_shift");
  const shift = useCurrentShift(canShift);
  const shiftOpen = Boolean(shift.data?.report);

  useShortcut(
    LOOKUP_SHORTCUT,
    () => {
      const input = document.getElementById(LOOKUP_INPUT_ID);
      if (input instanceof HTMLInputElement) {
        input.focus();
        input.select();
      }
    },
    { allowInInputs: true },
  );

  const setSearch = (next: CashierSearch) => {
    void navigate({ to: "/cashier", search: next, replace: true });
  };

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader
        title={t("title")}
        description={t("description")}
        icon={<Wallet />}
        actions={<ShortcutsDialog />}
      />
      <CashierNav />
      <ShiftBar />
      <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
        <LookupPanel
          query={query}
          onQueryChange={(q) => {
            setSearch({ ...search, q: q || undefined });
          }}
          selectedVisitId={visitId}
          onSelectVisit={(visit) => {
            setSearch({ ...search, visit });
          }}
        />
        <div className="flex min-w-0 flex-col gap-4">
          {visitId === undefined ? (
            <EmptyState
              icon={<MousePointerClick />}
              title={t("billing.pickTitle")}
              description={t("billing.pickDescription")}
            />
          ) : billing.isError ? (
            <AlertCard variant="danger" title={t("errors:title")}>
              {translateError(billing.error)}
            </AlertCard>
          ) : (
            <>
              <BillingPanel billing={billing.data} loading={billing.isPending} />
              {billing.data &&
              (isPositiveAmount(billing.data.balance.outstanding) || billing.data.invoices.length > 0) ? (
                <PaymentPanel billing={billing.data} shiftOpen={shiftOpen} />
              ) : null}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
