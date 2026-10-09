import { ArrowDown, ArrowUp, TriangleAlert } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";
import { cn } from "@/lib/utils";

import type { LabResult } from "../types";

type Value = LabResult["values"][number];

function flagTone(flag: string): { className: string; icon: typeof ArrowUp | null } {
  if (flag.startsWith("critical")) return { className: "bg-danger-bg text-danger-fg", icon: TriangleAlert };
  if (flag === "high") return { className: "bg-warning-bg text-warning-fg", icon: ArrowUp };
  if (flag === "low") return { className: "bg-warning-bg text-warning-fg", icon: ArrowDown };
  if (flag === "abnormal") return { className: "bg-warning-bg text-warning-fg", icon: TriangleAlert };
  return { className: "", icon: null };
}

/** Approved result values with their flags (icon and text, never color alone). */
export function ResultValues({ values, compact = false }: { values: readonly Value[]; compact?: boolean }) {
  const { t } = useTranslation("clinic");
  const language = useLanguage();
  return (
    <dl className={cn("grid gap-1", compact ? "text-xs" : "text-sm")}>
      {values.map((v) => {
        const tone = flagTone(v.flag);
        const Icon = tone.icon;
        const flagged = v.flag !== "" && v.flag !== "none" && v.flag !== "normal";
        return (
          <div
            key={v.parameter_code}
            className={cn("flex min-w-0 flex-wrap items-baseline gap-x-2 rounded-[6px] px-1.5 py-0.5", tone.className)}
          >
            <dt className="min-w-0 text-fg-muted">{pickName({ ar: v.name_ar, en: v.name_en }, language)}</dt>
            <dd className="ms-auto flex items-baseline gap-1 tabular font-semibold">
              {Icon ? <Icon className="size-3.5 self-center" aria-hidden="true" /> : null}
              <bdi>
                {v.value}
                {v.unit ? ` ${v.unit}` : ""}
              </bdi>
              {flagged ? <span className="sr-only">{t(`resultFlag.${flagKey(v.flag)}`)}</span> : null}
              {v.reference && !compact ? (
                <span className="text-xs font-normal text-muted">
                  (<bdi>{v.reference}</bdi>)
                </span>
              ) : null}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

function flagKey(flag: string): "high" | "low" | "critical" | "abnormal" {
  if (flag.startsWith("critical")) return "critical";
  if (flag === "high" || flag === "low") return flag;
  return "abnormal";
}
