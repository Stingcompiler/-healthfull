import { ShieldAlert } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { DateText } from "@/components/DateText";
import { MoneyText } from "@/components/MoneyText";
import { STATUS_STYLES, type ServiceLineState } from "@/components/status";
import { StatusBadge } from "@/components/StatusBadge";
import { formatNumber } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";
import { cn } from "@/lib/utils";

export interface ServiceLineCardProps {
  /** Already localized service name. */
  name: string;
  /** Optional secondary line: department, code, dose... */
  meta?: ReactNode;
  quantity: number;
  /** Server-computed amounts as decimal strings. Omit to hide prices (doctor view). */
  unitPrice?: string;
  total?: string;
  status: ServiceLineState;
  /** Performed under a perform-first authorization. */
  authorized?: boolean;
  orderedBy?: string;
  orderedAt?: string;
  actions?: ReactNode;
  className?: string;
}

export function ServiceLineCard({
  name,
  meta,
  quantity,
  unitPrice,
  total,
  status,
  authorized = false,
  orderedBy,
  orderedAt,
  actions,
  className,
}: ServiceLineCardProps) {
  const { t } = useTranslation();
  const language = useLanguage();
  return (
    <article
      data-slot="service-line-card"
      data-status={status}
      className={cn("card-surface relative flex min-w-0 flex-col gap-3 overflow-hidden p-4 ps-5", className)}
    >
      <span aria-hidden="true" className={cn("absolute inset-y-0 start-0 w-1", STATUS_STYLES[status].dotClassName)} />
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm leading-snug font-semibold text-fg">{name}</h3>
          {meta ? <div className="mt-0.5 text-xs text-muted">{meta}</div> : null}
        </div>
        <StatusBadge status={status} />
      </div>
      <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
        <dl className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
          <div className="flex gap-1">
            <dt>{t("serviceLine.qty")}</dt>
            <dd className="tabular font-semibold text-fg">{formatNumber(quantity, language)}</dd>
          </div>
          {unitPrice !== undefined ? (
            <div className="flex gap-1">
              <dt>{t("serviceLine.unitPrice")}</dt>
              <dd className="text-fg">
                <MoneyText value={unitPrice} currency={false} />
              </dd>
            </div>
          ) : null}
          {orderedBy ? <div>{t("serviceLine.orderedBy", { name: orderedBy })}</div> : null}
          {orderedAt ? <DateText value={orderedAt} format="relative" /> : null}
        </dl>
        {total !== undefined ? (
          <div className="ms-auto text-end">
            <div className="text-[11px] text-muted">{t("serviceLine.total")}</div>
            <MoneyText value={total} className="text-base font-semibold text-fg" />
          </div>
        ) : null}
      </div>
      {authorized || actions ? (
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3">
          {authorized ? (
            <span className="inline-flex items-center gap-1 text-xs font-medium text-warning-fg">
              <ShieldAlert className="size-3.5" aria-hidden="true" />
              {t("serviceLine.authorized")}
            </span>
          ) : (
            <span />
          )}
          {actions ? <div className="ms-auto flex flex-wrap items-center gap-2">{actions}</div> : null}
        </div>
      ) : null}
    </article>
  );
}
