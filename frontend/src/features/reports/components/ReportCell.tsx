import { useTranslation } from "react-i18next";

import { DateText } from "@/components/DateText";
import { MoneyText } from "@/components/MoneyText";
import { formatNumber, formatPercent } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";
import { cn } from "@/lib/utils";

import type { ReportCellValue, ReportColumnKind } from "../types";

/** A report value shown by its column kind: money, counts, days, minutes, dates, names, codes. */
export function ReportCell({
  value,
  kind,
  className,
}: {
  value: ReportCellValue | undefined;
  kind: ReportColumnKind;
  className?: string;
}) {
  const { t } = useTranslation("reports");
  const language = useLanguage();
  if (value === null || value === undefined || value === "") {
    return (
      <span className={cn("text-muted", className)} aria-label={t("viewer.noValue")}>
        —
      </span>
    );
  }
  if (typeof value === "object") {
    return <span className={className}>{pickName(value, language)}</span>;
  }
  switch (kind) {
    case "money":
      return <MoneyText value={String(value)} currency={false} toneNegative className={className} />;
    case "int":
      return <span className={cn("tabular", className)}>{formatNumber(Number(value), language)}</span>;
    case "days":
      return <span className={cn("tabular", className)}>{t("units.days", { count: Number(value) })}</span>;
    case "minutes":
      return <span className={cn("tabular", className)}>{t("units.minutes", { count: Number(value) })}</span>;
    case "percent":
      return <span className={cn("tabular", className)}>{formatPercent(String(value), language)}</span>;
    case "date":
      return <DateText value={String(value)} className={className} />;
    case "datetime":
      return <DateText value={String(value)} format="datetime" className={className} />;
    case "code":
      return <bdi className={cn("tabular", className)}>{String(value)}</bdi>;
    default:
      return (
        <span dir="auto" className={className}>
          {String(value)}
        </span>
      );
  }
}
