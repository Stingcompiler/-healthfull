import { Pill as PillIcon } from "lucide-react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";

import { usePrescriptions } from "../api";
import { PortalPage, PortalSection, Pill, Row } from "../components/PortalPage";
import type { PillTone } from "../lib/tones";
import { usePick } from "../lib/ui";
import type { PortalPrescriptionItem } from "../types";

const STATE_TONE: Record<PortalPrescriptionItem["state"], PillTone> = {
  dispensed: "success",
  partly_dispensed: "warning",
  not_dispensed: "neutral",
};

const ROUTES = new Set([
  "oral",
  "iv",
  "im",
  "sc",
  "topical",
  "inhaled",
  "rectal",
  "ophthalmic",
  "otic",
  "nasal",
  "other",
]);

/** Prescriptions with how to take them, and preparation for lab tests still to be done. */
export function PrescriptionsPage() {
  const { t } = useTranslation(["portal", "errors"]);
  const translateError = useTranslateError();
  const pick = usePick();
  const rx = usePrescriptions();

  return (
    <PortalPage title={t("prescriptions.title")} description={t("prescriptions.description")}>
      {rx.isPending ? (
        <Skeleton className="h-48" />
      ) : rx.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(rx.error)}
        </AlertCard>
      ) : (
        <>
          {rx.data.lab_instructions.length > 0 ? (
            <PortalSection title={t("prescriptions.labTitle")} testId="lab-instructions">
              <p className="text-xs text-muted">{t("prescriptions.labHint")}</p>
              <ul className="flex flex-col gap-2">
                {rx.data.lab_instructions.map((i) => (
                  <li key={i.line_id} className="rounded-control border border-info-border bg-info-bg p-3 text-info-fg">
                    <p className="font-semibold">{pick(i.test_name_ar, i.test_name_en)}</p>
                    <p className="text-sm">{pick(i.instructions_ar, i.instructions_en)}</p>
                  </li>
                ))}
              </ul>
            </PortalSection>
          ) : null}
          {rx.data.visits.length === 0 ? (
            <EmptyState icon={<PillIcon />} title={t("prescriptions.none")} />
          ) : (
            rx.data.visits.map((v) => (
              <PortalSection
                key={v.visit_number}
                testId="prescription-visit"
                title={
                  <span className="flex flex-col">
                    <span>{t("prescriptions.visit", { number: v.visit_number })}</span>
                    <span className="text-xs font-normal text-muted">
                      <DateText value={v.date} format="long" />
                      {v.prescriber
                        ? ` · ${t("prescriptions.prescriber", { name: pick(v.prescriber.name_ar, v.prescriber.name_en) })}`
                        : null}
                    </span>
                  </span>
                }
              >
                <ul className="flex flex-col divide-y divide-border">
                  {v.items.map((item) => (
                    <li key={item.line_id} className="flex flex-col gap-1 py-3" data-testid="prescription-item">
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <p className="min-w-0 font-semibold break-words text-fg">{pick(item.name_ar, item.name_en)}</p>
                        <Pill tone={STATE_TONE[item.state]}>{t(`prescriptions.state.${item.state}`)}</Pill>
                      </div>
                      <dl className="grid gap-x-6 sm:grid-cols-2">
                        <Row label={t("prescriptions.dose")}>
                          <bdi>{item.dose}</bdi>
                        </Row>
                        {ROUTES.has(item.route) ? (
                          <Row label={t("prescriptions.route")}>
                            {t(`prescriptions.routes.${item.route as "oral"}`)}
                          </Row>
                        ) : null}
                        {item.frequency_per_day ? (
                          <Row label={t("prescriptions.frequency")}>
                            <bdi className="tabular">{item.frequency_per_day}</bdi>
                          </Row>
                        ) : null}
                        {item.duration_days ? (
                          <Row label={t("prescriptions.duration")}>
                            <bdi className="tabular">{item.duration_days}</bdi>
                          </Row>
                        ) : null}
                        <Row label={t("prescriptions.quantity")}>
                          <bdi className="tabular">{item.quantity}</bdi>
                        </Row>
                      </dl>
                      {item.as_needed ? <p className="text-sm text-warning-fg">{t("prescriptions.asNeeded")}</p> : null}
                      {item.instructions ? (
                        <p className="rounded-control bg-subtle p-2 text-sm text-fg">
                          <span className="font-semibold">{t("prescriptions.instructions")}: </span>
                          <bdi>{item.instructions}</bdi>
                        </p>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </PortalSection>
            ))
          )}
        </>
      )}
    </PortalPage>
  );
}
