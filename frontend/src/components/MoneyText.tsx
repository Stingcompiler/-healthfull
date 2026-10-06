import { formatMoney, isNegativeAmount, type MoneyInput } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";
import { cn } from "@/lib/utils";

export interface MoneyTextProps {
  /** Decimal string from the API ("10000.00"); numbers allowed for literals only. */
  value: MoneyInput;
  /** Show the currency symbol. Default true. */
  currency?: boolean;
  /** Prefix positive values with +. */
  signed?: boolean;
  /** Color negative values as danger (credit notes, refunds). */
  toneNegative?: boolean;
  className?: string;
}

/**
 * Money in SDG, formatted with Intl for the current language, tabular
 * digits, isolated from surrounding bidi text so "10,000.00 ج.س." never
 * gets reordered inside Arabic sentences. Never does arithmetic.
 */
export function MoneyText({ value, currency = true, signed = false, toneNegative = false, className }: MoneyTextProps) {
  const language = useLanguage();
  const text = formatMoney(value, language, { currency, signed });
  const negative = isNegativeAmount(value);
  return (
    <bdi
      data-slot="money"
      data-negative={negative || undefined}
      className={cn("tabular font-medium whitespace-nowrap", toneNegative && negative && "text-danger-fg", className)}
    >
      {text}
    </bdi>
  );
}
