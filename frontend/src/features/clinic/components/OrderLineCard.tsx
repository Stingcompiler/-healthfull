import { Loader, ShieldAlert, Undo2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { ServiceLineCard } from "@/components/ServiceLineCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

import { lineBadgeState, useFrequencyText } from "../lib";
import type { DoctorLine } from "../types";
import { MetaParts } from "./MetaParts";
import { ResultValues } from "./ResultValues";

/** One order as its doctor sees it: progress, prescription, overrides, result. Never a price. */
export function OrderLineCard({ line, onWithdraw }: { line: DoctorLine; onWithdraw?: (line: DoctorLine) => void }) {
  const { t } = useTranslation("clinic");
  const frequencyText = useFrequencyText();
  const language = useLanguage();
  const rx = line.prescription;
  const cancellation = line.cancellation;
  return (
    <div data-testid="order-line" data-service-code={line.service_code} data-status={line.status}>
      <ServiceLineCard
        name={pickName({ ar: line.name_ar, en: line.name_en }, language)}
        quantity={Number(line.quantity)}
        status={lineBadgeState(line.status)}
        authorized={line.authorized}
        orderedAt={line.ordered_at}
        orderedBy={
          line.ordered_by ? pickName({ ar: line.ordered_by.name_ar, en: line.ordered_by.name_en }, language) : undefined
        }
        meta={
          <div className="flex flex-col gap-1.5">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <span>
                <bdi>{line.service_code}</bdi>
                {" · "}
                {t(`kind.${line.kind}`)}
              </span>
              {line.status === "in_progress" ? (
                <Badge variant="info" data-testid="line-in-progress">
                  <Loader aria-hidden="true" />
                  {t("orders.inProgress")}
                </Badge>
              ) : null}
            </div>
            {rx ? (
              <div className="text-fg-muted">
                <MetaParts
                  parts={[
                    rx.dose,
                    frequencyText(rx.frequency_code),
                    rx.duration_days ? t("rx.days", { count: rx.duration_days }) : "",
                    rx.as_needed ? t("rx.asNeeded") : "",
                    t(`route.${rx.route}`),
                  ]}
                />
                {rx.instructions ? <div>{rx.instructions}</div> : null}
              </div>
            ) : line.note ? (
              <div className="text-fg-muted">{line.note}</div>
            ) : null}
            {line.allergy_overrides.length > 0 ? (
              <div className="flex items-start gap-1 font-medium text-danger-fg">
                <ShieldAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
                <span>{t("orders.overridden", { reason: line.allergy_overrides[0]?.reason ?? "" })}</span>
              </div>
            ) : null}
            {cancellation ? (
              <div className="text-danger-fg">
                {t("orders.cancelledBecause", {
                  reason: pickName({ ar: cancellation.label_ar, en: cancellation.label_en }, language),
                })}
                {cancellation.note ? ` · ${cancellation.note}` : ""}
              </div>
            ) : null}
            {line.result ? (
              <div className="mt-1 rounded-control border border-border p-2" data-testid="line-result">
                <ResultValues values={line.result.values} compact />
              </div>
            ) : null}
          </div>
        }
        actions={
          onWithdraw && line.can_withdraw ? (
            <Button size="sm" variant="ghost" onClick={() => onWithdraw(line)}>
              <Undo2 aria-hidden="true" />
              {t("orders.withdraw")}
            </Button>
          ) : undefined
        }
      />
    </div>
  );
}
