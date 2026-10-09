import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";

import { isCritical, rangeText } from "../lib/flags";
import { useLabNames } from "../lib/use-lab-names";
import type { ResultValue } from "../types";
import { FlagBadge } from "./badges";

/** The values of one version with unit, flag and the range they were judged against. */
export function ResultValues({ values }: { values: readonly ResultValue[] }) {
  const { t } = useTranslation("lab");
  const names = useLabNames();
  if (values.length === 0) return <p className="text-sm text-muted">{t("versions.noValues")}</p>;
  return (
    <ul className="flex flex-col divide-y divide-border text-sm" data-testid="result-values">
      {values.map((v) => {
        const reference = rangeText(v.reference_low, v.reference_high, v.reference_text);
        return (
          <li
            key={v.parameter_id}
            className={cn(
              "flex flex-wrap items-center gap-x-3 gap-y-1 py-1.5",
              isCritical(v.flag) && "rounded-[6px] bg-danger-bg/40 px-1.5",
            )}
            data-testid="result-value"
            data-code={v.parameter_code}
            data-flag={v.flag}
          >
            <span className="min-w-0 flex-1 text-fg-muted">{names.text(v.name_ar, v.name_en)}</span>
            <bdi dir="ltr" className="tabular font-semibold">
              {v.value}
              {v.unit ? <span className="ms-1 text-xs font-normal text-muted">{v.unit}</span> : null}
            </bdi>
            {v.flag !== "none" && v.flag !== "normal" ? <FlagBadge flag={v.flag} /> : null}
            {reference ? (
              <span className="w-full text-xs text-muted sm:w-auto">
                {t("entry.reference")}: <bdi dir="ltr">{reference}</bdi>
              </span>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}
