import { Calculator } from "lucide-react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { MoneyText } from "@/components/MoneyText";
import { Button } from "@/components/ui/button";
import { useTranslateError } from "@/lib/api/translate-error";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

import { useEstimate } from "../api";
import { toOrderItem, type DraftItem } from "../draft";

/**
 * The center's optional estimated cost (FEATURES 3.8): the patient's share of the draft at
 * today's prices, computed by the server. Rendered only for holders of
 * clinical.view_estimated_cost; the server also refuses it unless the center turned it on.
 * The parent remounts it (key) when the draft changes, so a shown estimate always matches it.
 */
export function EstimatePanel({ visitId, draft }: { visitId: number; draft: readonly DraftItem[] }) {
  const { t } = useTranslation("clinic");
  const language = useLanguage();
  const estimate = useEstimate(visitId);
  const translateError = useTranslateError();
  const names = new Map(draft.map((d) => [d.serviceId, pickName({ ar: d.nameAr, en: d.nameEn }, language)]));

  return (
    <div className="flex flex-col gap-2" data-testid="estimate">
      <div>
        <Button
          variant="outline"
          size="sm"
          loading={estimate.isPending}
          disabled={draft.length === 0}
          onClick={() => {
            estimate.mutate({ items: draft.map((item) => toOrderItem(item, language)) });
          }}
          data-testid="estimate-show"
        >
          <Calculator aria-hidden="true" />
          {t("estimate.show")}
        </Button>
      </div>
      {estimate.isError ? (
        <AlertCard variant="warning" live title={t("estimate.error")}>
          {translateError(estimate.error)}
        </AlertCard>
      ) : null}
      {estimate.data ? (
        <section aria-label={t("estimate.title")} className="rounded-control border border-border p-3 text-sm">
          <h4 className="font-semibold text-fg">{t("estimate.title")}</h4>
          <p className="text-xs text-muted">{t("estimate.hint")}</p>
          <dl className="mt-2 flex flex-col gap-1">
            {estimate.data.lines.map((line, index) => (
              <div key={`${String(line.service_id)}-${String(index)}`} className="flex justify-between gap-3">
                <dt className="min-w-0 break-words text-fg-muted">{names.get(line.service_id) ?? ""}</dt>
                <dd>
                  <MoneyText value={line.patient_share} />
                </dd>
              </div>
            ))}
            <div className="flex justify-between gap-3 border-t border-border pt-1 font-semibold">
              <dt>{t("estimate.total")}</dt>
              <dd>
                <MoneyText value={estimate.data.total} />
              </dd>
            </div>
          </dl>
        </section>
      ) : null}
    </div>
  );
}
