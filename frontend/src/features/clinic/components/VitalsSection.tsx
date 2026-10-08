import { Activity, Plus } from "lucide-react";
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
import { pickName } from "@/lib/names";

import { useCreateVitals } from "../api";
import type { Vitals, VitalsInput } from "../types";

const DECIMAL_FIELDS = ["temperature_c", "weight_kg", "height_cm"] as const;
const INT_FIELDS = [
  "pulse_bpm",
  "respiratory_rate",
  "bp_systolic",
  "bp_diastolic",
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

/** Turn the typed readings into the request; the server checks ranges (no rule here). */
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

/** Vital signs of the visit (FEATURES 3.4): record and review. */
export function VitalsSection({
  visitId,
  vitals,
  open,
}: {
  visitId: number;
  vitals: readonly Vitals[];
  open: boolean;
}) {
  const { t } = useTranslation("clinic");
  const language = useLanguage();
  const canRecord = usePermission("clinical.record_vitals") && open;
  const create = useCreateVitals(visitId);
  const translateError = useTranslateError();
  const [values, setValues] = useState(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const filled = ORDER.some((f) => values[f].trim() !== "");

  /** One recorded set as label/value pairs with units; blood pressure as systolic/diastolic. */
  const readings = (v: Vitals): { key: string; label: string; value: string }[] => {
    const has = (x: unknown) => x != null && x !== "";
    const out: { key: string; label: string; value: string }[] = [];
    const add = (key: string, label: string, value: string) => out.push({ key, label, value });
    if (has(v.temperature_c))
      add("t", t("vitals.short.temperature_c"), t("vitals.tempValue", { value: v.temperature_c }));
    if (has(v.bp_systolic) && has(v.bp_diastolic))
      add("bp", t("vitals.short.bp"), t("vitals.bpValue", { sys: v.bp_systolic, dia: v.bp_diastolic }));
    if (has(v.pulse_bpm)) add("hr", t("vitals.short.pulse_bpm"), t("vitals.pulseValue", { value: v.pulse_bpm }));
    if (has(v.respiratory_rate))
      add("rr", t("vitals.short.respiratory_rate"), t("vitals.rrValue", { value: v.respiratory_rate }));
    if (has(v.spo2_percent))
      add("spo2", t("vitals.short.spo2_percent"), t("vitals.spo2Value", { value: v.spo2_percent }));
    if (has(v.weight_kg)) add("wt", t("vitals.short.weight_kg"), t("vitals.weightValue", { value: v.weight_kg }));
    if (has(v.height_cm)) add("ht", t("vitals.short.height_cm"), t("vitals.heightValue", { value: v.height_cm }));
    if (has(v.blood_glucose_mg_dl))
      add("glu", t("vitals.short.blood_glucose_mg_dl"), t("vitals.glucoseValue", { value: v.blood_glucose_mg_dl }));
    if (has(v.pain_score)) add("pain", t("vitals.short.pain_score"), t("vitals.painValue", { value: v.pain_score }));
    return out;
  };

  const submit = () => {
    setError(null);
    create.mutate(toInput(values), {
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
    <section aria-labelledby="vitals-heading" className="card-surface flex flex-col gap-4 p-4 md:p-5">
      <div className="flex items-center gap-2">
        <Activity className="size-4 text-muted" aria-hidden="true" />
        <h2 id="vitals-heading" className="text-base font-semibold text-fg">
          {t("vitals.title")}
        </h2>
      </div>

      {vitals.length > 0 ? (
        <ul className="flex flex-col gap-2">
          {vitals.slice(0, 3).map((v) => (
            <li key={v.id} className="rounded-control border border-border px-3 py-2 text-sm">
              <div className="mb-1 flex flex-wrap justify-between gap-2 text-xs text-muted">
                <span>
                  {v.recorded_by ? pickName({ ar: v.recorded_by.name_ar, en: v.recorded_by.name_en }, language) : ""}
                </span>
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
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted">{t("vitals.none")}</p>
      )}

      {canRecord ? (
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
            {ORDER.map((f) => (
              <div key={f} className="flex min-w-0 flex-col gap-1.5">
                <Label htmlFor={`vital-${f}`} className="text-xs">
                  {t(`vitals.field.${f}`)}
                </Label>
                <Input
                  id={`vital-${f}`}
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
            <Button type="submit" variant="outline" loading={create.isPending} disabled={!filled}>
              <Plus aria-hidden="true" />
              {t("vitals.record")}
            </Button>
          </div>
        </form>
      ) : null}
    </section>
  );
}
