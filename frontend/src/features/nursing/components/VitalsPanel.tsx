import { Activity, Save } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { AlertCard } from "@/components/AlertCard";
import { DateText } from "@/components/DateText";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useTranslateError } from "@/lib/api/translate-error";
import { usePermission } from "@/lib/auth/hooks";
import { useLanguage } from "@/lib/i18n-hooks";

import { useRecordVitals } from "../api";
import { nameOf } from "../lib";
import type { Vitals, VitalsInput } from "../types";

const DECIMAL_FIELDS = ["temperature_c", "weight_kg", "height_cm"] as const;
const INT_FIELDS = [
  "bp_systolic",
  "bp_diastolic",
  "pulse_bpm",
  "respiratory_rate",
  "spo2_percent",
  "blood_glucose_mg_dl",
  "pain_score",
] as const;
type Field = (typeof DECIMAL_FIELDS)[number] | (typeof INT_FIELDS)[number];
const ORDER: readonly Field[] = [
  "temperature_c",
  "bp_systolic",
  "bp_diastolic",
  "pulse_bpm",
  "respiratory_rate",
  "spo2_percent",
  "weight_kg",
  "height_cm",
  "blood_glucose_mg_dl",
  "pain_score",
];
const EMPTY = Object.fromEntries(ORDER.map((f) => [f, ""])) as Record<Field, string>;

/** The typed readings as the request; the server checks plausibility (no rule here). */
function toInput(values: Record<Field, string>): VitalsInput {
  const body: VitalsInput = { note: "" };
  for (const f of DECIMAL_FIELDS) {
    const v = values[f].trim();
    if (v) body[f] = v;
  }
  for (const f of INT_FIELDS) {
    const v = values[f].trim();
    if (v) body[f] = Number(v);
  }
  return body;
}

interface Reading {
  key: string;
  label: string;
  value: string;
}

function useReadings(): (v: Vitals) => Reading[] {
  const { t } = useTranslation("nursing");
  return (v) => {
    const out: Reading[] = [];
    const has = (x: unknown) => x !== null && x !== undefined && x !== "";
    const add = (key: Exclude<Field, "bp_systolic" | "bp_diastolic"> | "bp", value: string) => {
      out.push({ key, label: t(`vitals.short.${key}`), value });
    };
    if (has(v.temperature_c)) add("temperature_c", t("vitals.value.temperature_c", { value: v.temperature_c }));
    if (has(v.bp_systolic) && has(v.bp_diastolic))
      add("bp", t("vitals.value.bp", { sys: v.bp_systolic, dia: v.bp_diastolic }));
    if (has(v.pulse_bpm)) add("pulse_bpm", t("vitals.value.pulse_bpm", { value: v.pulse_bpm }));
    if (has(v.respiratory_rate))
      add("respiratory_rate", t("vitals.value.respiratory_rate", { value: v.respiratory_rate }));
    if (has(v.spo2_percent)) add("spo2_percent", t("vitals.value.spo2_percent", { value: v.spo2_percent }));
    if (has(v.weight_kg)) add("weight_kg", t("vitals.value.weight_kg", { value: v.weight_kg }));
    if (has(v.height_cm)) add("height_cm", t("vitals.value.height_cm", { value: v.height_cm }));
    if (has(v.blood_glucose_mg_dl))
      add("blood_glucose_mg_dl", t("vitals.value.blood_glucose_mg_dl", { value: v.blood_glucose_mg_dl }));
    if (has(v.pain_score)) add("pain_score", t("vitals.value.pain_score", { value: v.pain_score }));
    return out;
  };
}

/** Record vital signs (FEATURES 3.4) with large tablet inputs, and the sets recorded so far. */
export function VitalsPanel({ visitId, vitals, open }: { visitId: number; vitals: readonly Vitals[]; open: boolean }) {
  const { t } = useTranslation("nursing");
  const language = useLanguage();
  const canRecord = usePermission("clinical.record_vitals") && open;
  const record = useRecordVitals(visitId);
  const translateError = useTranslateError();
  const readings = useReadings();
  const [values, setValues] = useState(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const filled = ORDER.some((f) => values[f].trim() !== "");

  const submit = () => {
    setError(null);
    record.mutate(toInput(values), {
      onSuccess: () => {
        setValues(EMPTY);
        toast.success(t("vitals.savedToast"));
      },
      onError: (e) => {
        setError(translateError(e));
      },
    });
  };

  return (
    <section aria-labelledby="nursing-vitals" className="card-surface flex flex-col gap-4 p-4 md:p-5">
      <h2 id="nursing-vitals" className="flex items-center gap-2 text-base font-semibold text-fg">
        <Activity className="size-4 text-muted" aria-hidden="true" />
        {t("vitals.title")}
      </h2>

      {canRecord ? (
        <form
          className="flex flex-col gap-3"
          data-testid="vitals-form"
          onSubmit={(e) => {
            e.preventDefault();
            if (filled) submit();
          }}
        >
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
            {ORDER.map((f) => (
              <div key={f} className="flex min-w-0 flex-col justify-end gap-1.5">
                <Label htmlFor={`nv-${f}`} className="text-xs">
                  {t(`vitals.field.${f}`)}
                </Label>
                <Input
                  id={`nv-${f}`}
                  className="h-12 text-lg"
                  inputMode={(DECIMAL_FIELDS as readonly string[]).includes(f) ? "decimal" : "numeric"}
                  dir="ltr"
                  value={values[f]}
                  onChange={(e) => {
                    setValues((prev) => ({ ...prev, [f]: e.target.value }));
                  }}
                />
              </div>
            ))}
          </div>
          {error ? (
            <AlertCard variant="danger" live title={t("vitals.saveError")}>
              {error}
            </AlertCard>
          ) : null}
          <div className="flex justify-end">
            <Button
              type="submit"
              size="lg"
              className="h-12 max-sm:w-full"
              loading={record.isPending}
              disabled={!filled}
              data-testid="vitals-save"
            >
              <Save aria-hidden="true" />
              {t("vitals.record")}
            </Button>
          </div>
        </form>
      ) : null}

      {vitals.length === 0 ? (
        <p className="text-sm text-muted">{t("vitals.none")}</p>
      ) : (
        <ul className="flex flex-col gap-2" data-testid="vitals-list">
          {vitals.map((v) => (
            <li key={v.id} className="rounded-control border border-border px-3 py-2 text-sm">
              <div className="mb-1 flex flex-wrap justify-between gap-2 text-xs text-muted">
                <span>{v.recorded_by ? t("vitals.by", { name: nameOf(v.recorded_by, language) }) : null}</span>
                <DateText value={v.recorded_at} format="datetime" />
              </div>
              <dl className="flex flex-wrap gap-x-4 gap-y-1">
                {readings(v).map(({ key, label, value }) => (
                  <div key={key} className="flex gap-1">
                    <dt className="text-muted">{label}</dt>
                    <dd className="tabular font-semibold text-fg">
                      <bdi>{value}</bdi>
                    </dd>
                  </div>
                ))}
              </dl>
              {v.note ? (
                <p dir="auto" className="mt-1 text-start text-xs text-pretty break-words text-muted">
                  {v.note}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
