import { Wallet } from "lucide-react";
import { useTranslation } from "react-i18next";

import { MoneyText } from "@/components/MoneyText";
import { Skeleton } from "@/components/ui/skeleton";
import { isNegativeAmount, isZeroAmount } from "@/lib/format";

import { useBalance } from "../api";
import { QueryErrorAlert } from "./QueryErrorAlert";

/**
 * The person's money position (FEATURES 1.5): credit, spendable credit, unverified transfers and
 * open invoices. Figures come from the server as decimal strings; nothing is computed here.
 */
export function BalanceCard({ patientId }: { patientId: number }) {
  const { t } = useTranslation("patients");
  const balance = useBalance(patientId, true);
  const b = balance.data;
  return (
    <section
      aria-labelledby="balance-heading"
      className="card-surface flex flex-col gap-3 p-4 md:p-5"
      data-testid="balance"
    >
      <h2 id="balance-heading" className="flex items-center gap-2 text-base font-semibold text-fg">
        <Wallet className="size-5 text-muted" aria-hidden="true" />
        {t("balance.title")}
      </h2>
      {balance.isError ? (
        <QueryErrorAlert
          title={t("balance.loadFailed")}
          error={balance.error}
          onRetry={() => void balance.refetch()}
          retrying={balance.isFetching}
        />
      ) : !b ? (
        <Skeleton className="h-24" />
      ) : (
        <>
          <dl className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <dt className="text-muted">{t("balance.credit")}</dt>
              <dd className="font-semibold">
                <MoneyText value={b.credit} />
              </dd>
            </div>
            <div>
              <dt className="text-muted">{t("balance.spendable")}</dt>
              <dd className="font-semibold">
                <MoneyText value={b.spendable} />
              </dd>
            </div>
            <div>
              <dt className="text-muted">{t("balance.pending")}</dt>
              <dd className="font-semibold">
                <MoneyText value={b.pending} />
              </dd>
            </div>
            <div>
              <dt className="text-muted">{t("balance.outstanding")}</dt>
              <dd className="font-semibold">
                <MoneyText value={b.outstanding} />
              </dd>
            </div>
          </dl>
          <p className="text-sm font-medium text-fg">
            {isZeroAmount(b.net) ? (
              t("balance.settled")
            ) : isNegativeAmount(b.net) ? (
              <>
                {t("balance.netCredit")} <MoneyText value={b.net.replace(/^-/, "")} />
              </>
            ) : (
              <>
                {t("balance.netOwes")} <MoneyText value={b.net} />
              </>
            )}
          </p>
          {b.invoices.length > 0 ? (
            <ul className="grid gap-1 text-sm" aria-label={t("balance.openInvoices")}>
              {b.invoices.map((inv) => (
                <li key={inv.invoice_id} className="flex justify-between gap-2">
                  <bdi className="tabular text-muted">{inv.number}</bdi>
                  <MoneyText value={inv.outstanding} />
                </li>
              ))}
            </ul>
          ) : null}
        </>
      )}
    </section>
  );
}
