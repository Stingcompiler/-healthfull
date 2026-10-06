import { formatDate, formatRelative, toDate, type DateFormat } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";
import { cn } from "@/lib/utils";

export interface DateTextProps {
  value: string | number | Date;
  format?: DateFormat | "relative";
  className?: string;
}

/** A date in the center time zone, localized; full timestamp in the tooltip. */
export function DateText({ value, format = "date", className }: DateTextProps) {
  const language = useLanguage();
  const date = toDate(value);
  const text = format === "relative" ? formatRelative(date, language) : formatDate(date, language, format);
  const title = formatDate(date, language, "datetime");
  return (
    <time dateTime={date.toISOString()} title={title} className={cn("tabular whitespace-nowrap", className)}>
      {text}
    </time>
  );
}
