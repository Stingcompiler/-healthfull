import { Activity, ChevronDown, HeartPulse, Pill, ShieldAlert, Stethoscope, TestTube } from "lucide-react";
import { useId, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Can } from "@/components/Can";
import { DateText } from "@/components/DateText";
import { PatientCard } from "@/components/PatientCard";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { formatNumber } from "@/lib/format";
import { useBreakpoint } from "@/lib/hooks/use-media-query";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";
import { cn } from "@/lib/utils";

import { usePatientSummary } from "../api";
import { toPatientCard, useFrequencyText } from "../lib";
import type { Workspace } from "../types";
import { AllergyManager } from "./AllergyManager";
import { ConditionManager } from "./ConditionManager";
import { MetaParts } from "./MetaParts";
import { QueryError } from "./QueryError";
import { ResultValues } from "./ResultValues";

/**
 * What a doctor sees on opening the file (FEATURES 3.1): allergies first, then the rest. Beside
 * the tabs from lg; below lg the patient card (with its allergies) stays on top and the rest
 * folds behind a toggle, so the note and orders start on the first screen.
 */
export function SummaryPanel({ workspace }: { workspace: Workspace }) {
  const { t } = useTranslation("clinic");
  const frequencyText = useFrequencyText();
  const language = useLanguage();
  const summary = usePatientSummary(workspace.patient.id);
  const [allergiesOpen, setAllergiesOpen] = useState(false);
  const [conditionsOpen, setConditionsOpen] = useState(false);
  const wide = useBreakpoint("lg");
  const [expanded, setExpanded] = useState(false);
  const detailsId = useId();
  const showDetails = wide || expanded;
  const data = summary.data;
  const latestVitals = workspace.vitals[0];

  return (
    <aside aria-label={t("summary.label")} className="flex min-w-0 flex-col gap-3" data-testid="summary-panel">
      <PatientCard
        patient={toPatientCard(
          workspace.patient,
          workspace.allergies,
          workspace.allergies_recorded,
          workspace.visit.payer,
          language,
        )}
        actions={
          <Can permission="clinical.manage_allergies">
            <Button size="sm" variant="outline" onClick={() => setAllergiesOpen(true)} data-testid="manage-allergies">
              <ShieldAlert aria-hidden="true" />
              {t("summary.allergies")}
            </Button>
          </Can>
        }
      />
      <AllergyManager patientId={workspace.patient.id} open={allergiesOpen} onOpenChange={setAllergiesOpen} />
      <ConditionManager patientId={workspace.patient.id} open={conditionsOpen} onOpenChange={setConditionsOpen} />

      {wide ? null : (
        <Button
          variant="outline"
          className="justify-between"
          aria-expanded={expanded}
          aria-controls={detailsId}
          onClick={() => setExpanded((v) => !v)}
          data-testid="summary-toggle"
        >
          {expanded ? t("summary.hide") : t("summary.show")}
          <ChevronDown aria-hidden="true" className={cn("transition-transform", expanded && "rotate-180")} />
        </Button>
      )}

      {!showDetails ? null : summary.isError ? (
        <QueryError
          title={t("summary.loadError")}
          error={summary.error}
          onRetry={() => void summary.refetch()}
          retrying={summary.isFetching}
        />
      ) : !data ? (
        <Skeleton className="h-48" />
      ) : (
        <div id={detailsId} className="card-surface flex flex-col divide-y divide-border" data-testid="summary-details">
          <Section
            icon={<HeartPulse />}
            title={t("summary.conditions")}
            action={
              <Can permission="clinical.manage_conditions">
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setConditionsOpen(true)}
                  data-testid="manage-conditions"
                >
                  {t("summary.manage")}
                </Button>
              </Can>
            }
          >
            {data.conditions.length === 0 ? (
              <Empty>{t("summary.noConditions")}</Empty>
            ) : (
              <ul className="flex flex-wrap gap-1.5">
                {data.conditions.map((c) => (
                  <li key={c.id} className="rounded-full bg-subtle px-2.5 py-1 text-xs font-medium text-fg">
                    {c.icd10 ? <bdi className="me-1 tabular text-muted">{c.icd10.code}</bdi> : null}
                    {c.name || (c.icd10 ? pickName({ ar: c.icd10.title_ar, en: c.icd10.title_en }, language) : "")}
                  </li>
                ))}
              </ul>
            )}
          </Section>

          {latestVitals ? (
            <Section icon={<Activity />} title={t("summary.latestVitals")}>
              <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs sm:grid-cols-3 lg:grid-cols-2">
                {latestVitals.temperature_c ? (
                  <Vital
                    label={t("vitals.temperature")}
                    value={t("vitals.tempValue", { value: latestVitals.temperature_c })}
                  />
                ) : null}
                {latestVitals.bp_systolic != null && latestVitals.bp_diastolic != null ? (
                  <Vital
                    label={t("vitals.bp")}
                    value={t("vitals.bpValue", { sys: latestVitals.bp_systolic, dia: latestVitals.bp_diastolic })}
                  />
                ) : null}
                {latestVitals.pulse_bpm != null ? (
                  <Vital
                    label={t("vitals.pulse")}
                    value={t("vitals.pulseValue", { value: formatNumber(latestVitals.pulse_bpm, language) })}
                  />
                ) : null}
                {latestVitals.spo2_percent != null ? (
                  <Vital label={t("vitals.spo2")} value={t("vitals.spo2Value", { value: latestVitals.spo2_percent })} />
                ) : null}
                {latestVitals.weight_kg ? (
                  <Vital
                    label={t("vitals.weight")}
                    value={t("vitals.weightValue", { value: latestVitals.weight_kg })}
                  />
                ) : null}
              </dl>
            </Section>
          ) : null}

          <Section icon={<Pill />} title={t("summary.medications")}>
            {data.active_medications.length === 0 ? (
              <Empty>{t("summary.noMedications")}</Empty>
            ) : (
              <ul className="flex flex-col gap-1.5 text-sm">
                {data.active_medications.map((m) => (
                  <li key={m.line_id} className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-2">
                    <span className="min-w-0 font-medium break-words text-fg">
                      {pickName({ ar: m.name_ar, en: m.name_en }, language)}
                    </span>
                    <span className="text-xs text-muted">
                      <MetaParts
                        parts={[
                          m.dose,
                          frequencyText(m.frequency_code),
                          m.duration_days ? t("rx.days", { count: m.duration_days }) : "",
                        ]}
                      />
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <Section icon={<TestTube />} title={t("summary.latestResults")}>
            {data.latest_results.length === 0 ? (
              <Empty>{t("summary.noResults")}</Empty>
            ) : (
              <ul className="flex flex-col gap-3">
                {data.latest_results.slice(0, 3).map((r) => (
                  <li key={r.id} className="flex flex-col gap-1">
                    <div className="flex flex-wrap items-baseline justify-between gap-x-2 text-sm">
                      <span className="font-medium text-fg">
                        {pickName({ ar: r.name_ar, en: r.name_en }, language)}
                      </span>
                      {r.approved_at ? <DateText value={r.approved_at} className="text-xs text-muted" /> : null}
                    </div>
                    <ResultValues values={r.values} compact />
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <Section icon={<Stethoscope />} title={t("summary.recentVisits")}>
            {data.recent_visits.length === 0 ? (
              <Empty>{t("summary.noVisits")}</Empty>
            ) : (
              <ul className="flex flex-col gap-1.5 text-sm">
                {data.recent_visits.map((v) => (
                  <li
                    key={v.id}
                    className={cn(
                      "flex min-w-0 flex-wrap items-baseline justify-between gap-x-2",
                      v.id === workspace.visit.id && "font-semibold",
                    )}
                  >
                    <span className="min-w-0 break-words text-fg">
                      {v.department ? pickName({ ar: v.department.name_ar, en: v.department.name_en }, language) : "—"}
                      {v.doctor ? (
                        <span className="text-muted">
                          {" "}
                          · {pickName({ ar: v.doctor.name_ar, en: v.doctor.name_en }, language)}
                        </span>
                      ) : null}
                    </span>
                    <DateText value={v.created_at} className="text-xs text-muted" />
                  </li>
                ))}
              </ul>
            )}
          </Section>
        </div>
      )}
    </aside>
  );
}

function Section({
  icon,
  title,
  action,
  children,
}: {
  icon: ReactNode;
  title: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="flex flex-col gap-2 p-4">
      <div className="flex items-center gap-2">
        <span className="text-muted [&_svg]:size-4" aria-hidden="true">
          {icon}
        </span>
        <h2 className="text-sm font-semibold text-fg">{title}</h2>
        {action ? <div className="ms-auto">{action}</div> : null}
      </div>
      {children}
    </section>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="text-xs text-muted">{children}</p>;
}

function Vital({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col">
      <dt className="text-muted">{label}</dt>
      <dd className="tabular font-semibold text-fg">
        <bdi>{value}</bdi>
      </dd>
    </div>
  );
}
