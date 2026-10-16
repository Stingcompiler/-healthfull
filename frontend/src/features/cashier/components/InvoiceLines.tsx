import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { MoneyText } from "@/components/MoneyText";
import type { ServiceLineState } from "@/components/status";
import { StatusBadge } from "@/components/StatusBadge";
import { formatNumber } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";
import { cn } from "@/lib/utils";

import { negate } from "../lib/money";

export interface InvoiceLineRow {
  id: number | string;
  /** Already localized service name. */
  name: string;
  /** Payer, "not covered" and "pre-approval" badges, code... */
  meta?: ReactNode;
  quantity: number;
  /** Server-computed amounts as decimal strings. */
  gross: string;
  discount: string;
  payerShare: string;
  patientShare: string;
  /** Shown (approved invoices) when not null. */
  outstanding?: string | null;
  status: ServiceLineState;
  /** The line needs a decision (not covered, pre-approval missing): the only tinted row. */
  needsDecision?: boolean;
  actions?: ReactNode;
}

/**
 * The lines of one invoice as ONE table-shaped surface. At md and up it is a dense table with
 * the payer and patient amounts aligned in their own columns; on a phone the same markup stacks
 * into rows (a label beside each amount). Status is one text badge; there is no edge stripe.
 * The amount the patient pays is the strongest figure of a row.
 */
export function InvoiceLines({ lines, caption }: { lines: readonly InvoiceLineRow[]; caption: string }) {
  const { t } = useTranslation("cashier");
  const language = useLanguage();
  const showDiscount = lines.some((l) => l.discount !== "0.00");
  const showOutstanding = lines.some((l) => l.outstanding !== undefined && l.outstanding !== null);
  const showActions = lines.some((l) => Boolean(l.actions));

  const th = "px-2.5 py-2 text-xs font-medium text-muted md:table-cell";
  const thNum = cn(th, "md:text-end");
  const td = "md:table-cell md:px-2.5 md:py-3 md:align-middle";
  const amount = cn(td, "col-span-2 flex items-baseline justify-between gap-3 md:text-end md:whitespace-nowrap");
  const label = "text-xs text-muted md:sr-only";

  return (
    <div className="overflow-x-auto">
      <table aria-label={caption} className="block w-full border-collapse text-sm md:table" data-slot="invoice-lines">
        <thead className="sr-only md:not-sr-only md:table-header-group">
          <tr className="md:table-row md:border-b md:border-border md:bg-subtle">
            <th scope="col" className={cn(th, "md:ps-4 md:text-start")}>
              {t("invoice.service")}
            </th>
            <th scope="col" className={thNum}>
              {t("invoice.qty")}
            </th>
            <th scope="col" className={thNum}>
              {t("invoice.gross")}
            </th>
            {showDiscount ? (
              <th scope="col" className={thNum}>
                {t("invoice.discount")}
              </th>
            ) : null}
            <th scope="col" className={thNum}>
              {t("invoice.payerShare")}
            </th>
            <th scope="col" className={thNum}>
              {t("invoice.patientShare")}
            </th>
            {showOutstanding ? (
              <th scope="col" className={thNum}>
                {t("invoice.outstanding")}
              </th>
            ) : null}
            {showActions ? (
              <th scope="col" className={cn(th, "md:pe-4")}>
                <span className="sr-only">{t("invoice.lineActions")}</span>
              </th>
            ) : null}
          </tr>
        </thead>
        <tbody className="block divide-y divide-border md:table-row-group">
          {lines.map((line) => {
            const cancelled = line.status === "cancelled";
            return (
              <tr
                key={line.id}
                data-slot="invoice-line"
                data-testid="invoice-line"
                data-status={line.status}
                data-decision={line.needsDecision ? "true" : undefined}
                className={cn(
                  "grid grid-cols-2 gap-x-6 gap-y-1.5 px-4 py-3 md:table-row md:p-0",
                  line.needsDecision && "bg-warning-bg",
                )}
              >
                <td className={cn(td, "col-span-2 min-w-0 md:w-full md:max-w-0 md:min-w-44 md:ps-4")}>
                  <div className="flex min-w-0 items-center gap-2">
                    <span
                      className={cn("min-w-0 font-medium break-words text-fg", cancelled && "text-muted line-through")}
                    >
                      {line.name}
                    </span>
                    <StatusBadge status={line.status} size="sm" className="shrink-0 whitespace-nowrap" />
                  </div>
                  {line.meta ? (
                    <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted [&_[data-slot=badge]]:max-w-full [&_[data-slot=badge]]:shrink [&_[data-slot=badge]]:rounded-xl [&_[data-slot=badge]]:whitespace-normal">
                      {line.meta}
                    </div>
                  ) : null}
                </td>
                <td className={cn(amount, "col-span-1")}>
                  <span className={label}>{t("invoice.qty")}</span>
                  <span className="tabular">{formatNumber(line.quantity, language)}</span>
                </td>
                <td className={cn(amount, "col-span-1")}>
                  <span className={label}>{t("invoice.gross")}</span>
                  <MoneyText value={line.gross} currency={false} />
                </td>
                {showDiscount ? (
                  <td className={amount}>
                    <span className={label}>{t("invoice.discount")}</span>
                    {line.discount !== "0.00" ? (
                      <MoneyText value={negate(line.discount)} currency={false} />
                    ) : (
                      <span className="text-muted">—</span>
                    )}
                  </td>
                ) : null}
                <td className={cn(amount, "text-muted")} data-testid="payer-share">
                  <span className={label}>{t("invoice.payerShare")}</span>
                  <MoneyText value={line.payerShare} currency={false} className="font-normal" />
                </td>
                <td className={cn(amount, "text-base text-fg")} data-testid="patient-share">
                  <span className={label}>{t("invoice.patientShare")}</span>
                  <MoneyText value={line.patientShare} currency={false} className="font-semibold" />
                </td>
                {showOutstanding ? (
                  <td className={amount}>
                    <span className={label}>{t("invoice.outstanding")}</span>
                    {line.outstanding !== undefined && line.outstanding !== null ? (
                      <MoneyText value={line.outstanding} currency={false} />
                    ) : null}
                  </td>
                ) : null}
                {showActions ? (
                  <td className={cn(td, "flex items-center justify-end md:pe-4 md:text-end")}>{line.actions}</td>
                ) : null}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
