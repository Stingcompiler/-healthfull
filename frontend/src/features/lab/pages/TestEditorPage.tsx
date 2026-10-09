import { zodResolver } from "@hookform/resolvers/zod";
import { Link, useParams } from "@tanstack/react-router";
import { BookOpen, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { AlertCard } from "@/components/AlertCard";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Form, SelectField, SwitchField, TextField } from "@/components/form";
import { ArrowBack } from "@/components/icons";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";
import { vmsg } from "@/lib/validation";

import { useDeleteRange, useLabTest, useUpdateTest } from "../api";
import { ParameterDialog, RangeDialog } from "../components/CatalogDialogs";
import { LabNav } from "../components/LabNav";
import { DAYS_PER_YEAR } from "../lib/ages";
import { rangeText } from "../lib/flags";
import { useLabNames } from "../lib/use-lab-names";
import { SAMPLE_TYPES, type LabParameter, type LabRange, type LabTest, type SampleType } from "../types";

const settingsSchema = z.object({
  sample_type: z.string().min(1, vmsg("validation.selectOption")),
  container: z.string().trim().max(60),
  method: z.string().trim().max(100),
  turnaround_minutes: z
    .string()
    .trim()
    .regex(/^[1-9][0-9]{0,4}$/, vmsg("validation.number")),
  instructions_ar: z.string().trim().max(300),
  instructions_en: z.string().trim().max(300),
  sort_order: z.string().regex(/^[0-9]{1,5}$/, vmsg("validation.number")),
  active: z.boolean(),
});
type SettingsValues = z.infer<typeof settingsSchema>;

/** Edits one test of the catalog (FEATURES 9.1): sample, turnaround, parameters and ranges. */
export function TestEditorPage() {
  const { t } = useTranslation(["lab", "errors"]);
  const translateError = useTranslateError();
  const names = useLabNames();
  const { testId } = useParams({ strict: false });
  const id = Number(testId);
  const test = useLabTest(id);

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader
        title={test.data ? names.test(test.data) : t("catalog.title")}
        eyebrow={test.data ? <bdi>{test.data.code}</bdi> : undefined}
        icon={<BookOpen />}
        actions={
          <Button asChild variant="outline">
            <Link to="/lab/catalog">
              <ArrowBack aria-hidden="true" />
              {t("catalog.back")}
            </Link>
          </Button>
        }
      />
      <LabNav />
      {test.isPending ? (
        <Skeleton className="h-96" />
      ) : test.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(test.error)}
        </AlertCard>
      ) : (
        <div className="grid min-w-0 gap-4 xl:grid-cols-[22rem_minmax(0,1fr)] xl:items-start">
          <SettingsCard key={test.data.id} test={test.data} />
          <ParametersCard test={test.data} />
        </div>
      )}
    </div>
  );
}

function SettingsCard({ test }: { test: LabTest }) {
  const { t } = useTranslation(["lab", "common", "errors"]);
  const translateError = useTranslateError();
  const update = useUpdateTest(test.id);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const form = useForm<SettingsValues>({
    resolver: zodResolver(settingsSchema),
    defaultValues: {
      sample_type: test.sample_type,
      container: test.container,
      method: test.method,
      turnaround_minutes: String(test.turnaround_minutes),
      instructions_ar: test.instructions_ar,
      instructions_en: test.instructions_en,
      sort_order: String(test.sort_order),
      active: test.active,
    },
  });
  const submit = form.handleSubmit(async (v) => {
    setError(null);
    setSaved(false);
    try {
      await update.mutateAsync({
        sample_type: v.sample_type as SampleType,
        container: v.container,
        method: v.method,
        turnaround_minutes: Number(v.turnaround_minutes),
        instructions_ar: v.instructions_ar,
        instructions_en: v.instructions_en,
        sort_order: Number(v.sort_order),
        active: v.active,
      });
      setSaved(true);
    } catch (e) {
      setError(translateError(e));
    }
  });
  return (
    <section className="card-surface flex min-w-0 flex-col gap-3 p-4 md:p-5" data-testid="test-settings">
      <h2 className="text-base font-semibold">{t("catalog.settings")}</h2>
      <Form {...form}>
        <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4">
          <SelectField
            control={form.control}
            name="sample_type"
            label={t("catalog.sampleType")}
            options={SAMPLE_TYPES.map((s) => ({ value: s, label: t(`sampleType.${s}`) }))}
            required
          />
          <TextField control={form.control} name="container" label={t("catalog.container")} maxLength={60} />
          <TextField control={form.control} name="method" label={t("catalog.method")} maxLength={100} />
          <TextField
            control={form.control}
            name="turnaround_minutes"
            label={t("catalog.turnaround")}
            type="number"
            inputMode="numeric"
            dir="ltr"
            required
          />
          <TextField
            control={form.control}
            name="instructions_ar"
            label={t("catalog.instructionsAr")}
            dir="rtl"
            maxLength={300}
          />
          <TextField
            control={form.control}
            name="instructions_en"
            label={t("catalog.instructionsEn")}
            dir="ltr"
            maxLength={300}
          />
          <TextField
            control={form.control}
            name="sort_order"
            label={t("catalog.sortOrder")}
            type="number"
            inputMode="numeric"
            dir="ltr"
          />
          <SwitchField
            control={form.control}
            name="active"
            label={t("catalog.testActive")}
            description={t("catalog.testActiveHint")}
          />
          {error ? (
            <AlertCard variant="danger" title={t("errors:title")} live>
              {error}
            </AlertCard>
          ) : null}
          {saved ? (
            <AlertCard variant="success" title={t("catalog.saved")} live>
              {null}
            </AlertCard>
          ) : null}
          <div>
            <Button type="submit" loading={form.formState.isSubmitting} data-testid="save-test">
              {t("common:actions.save")}
            </Button>
          </div>
        </form>
      </Form>
    </section>
  );
}

/** The age band of a range: "All ages", "From 18 years", "1 year to 12 years". */
function AgeBand({ range }: { range: LabRange }) {
  const { t } = useTranslation("lab");
  const fmt = (days: number) =>
    days % DAYS_PER_YEAR === 0 && days > 0
      ? t("catalog.ageYears", { count: days / DAYS_PER_YEAR })
      : t("catalog.ageDays", { count: days });
  if (range.age_max_days === null && range.age_min_days === 0) return <>{t("catalog.allAges")}</>;
  if (range.age_max_days === null) return <>{t("catalog.ageFromOnly", { from: fmt(range.age_min_days) })}</>;
  return <>{t("catalog.ageBetween", { from: fmt(range.age_min_days), to: fmt(range.age_max_days) })}</>;
}

function ParametersCard({ test }: { test: LabTest }) {
  const { t } = useTranslation(["lab", "common"]);
  const names = useLabNames();
  const del = useDeleteRange();
  const [editing, setEditing] = useState<LabParameter | null>(null);
  const [adding, setAdding] = useState(false);
  const [rangeFor, setRangeFor] = useState<{ parameter: LabParameter; range: LabRange | null } | null>(null);
  const [deleting, setDeleting] = useState<LabRange | null>(null);

  return (
    <section className="card-surface flex min-w-0 flex-col gap-3 p-4 md:p-5" data-testid="test-parameters">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold">{t("catalog.parameters")}</h2>
        <Button
          variant="outline"
          onClick={() => {
            setAdding(true);
          }}
          data-testid="add-parameter"
        >
          <Plus aria-hidden="true" />
          {t("catalog.addParameter")}
        </Button>
      </div>
      {test.parameters.length === 0 ? <p className="text-sm text-muted">{t("catalog.noParameters")}</p> : null}
      <ul className="flex flex-col gap-3">
        {test.parameters.map((p) => (
          <li
            key={p.id}
            className="flex min-w-0 flex-col gap-2 rounded-control border border-border p-3"
            data-testid="parameter-row"
            data-code={p.code}
          >
            <div className="flex flex-wrap items-start justify-between gap-2">
              <span className="flex min-w-0 flex-col">
                <span className="font-medium">
                  {names.text(p.name_ar, p.name_en)}
                  {p.unit ? (
                    <bdi dir="ltr" className="ms-1 text-xs text-muted">
                      ({p.unit})
                    </bdi>
                  ) : null}
                </span>
                <span className="text-xs text-muted">
                  <bdi>{p.code}</bdi> · {t(`valueType.${p.value_type}`)}
                  {p.value_type === "choice" ? (
                    <>
                      {" · "}
                      <bdi>{p.choices.join(" / ")}</bdi>
                    </>
                  ) : null}
                </span>
              </span>
              <span className="flex flex-wrap items-center gap-1">
                {p.active ? null : <Badge variant="neutral">{t("catalog.inactive")}</Badge>}
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={t("catalog.editParameterNamed", { name: names.text(p.name_ar, p.name_en) })}
                  onClick={() => {
                    setEditing(p);
                  }}
                >
                  <Pencil aria-hidden="true" />
                </Button>
              </span>
            </div>
            <ul className="flex flex-col gap-1 text-sm">
              {p.ranges.map((r) => (
                <li
                  key={r.id}
                  className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-[6px] bg-subtle px-2 py-1"
                  data-testid="range-row"
                >
                  <span className="font-medium">{t(`sex.${r.sex}`)}</span>
                  <span className="text-muted">
                    <AgeBand range={r} />
                  </span>
                  <bdi dir="ltr">{rangeText(r.low, r.high, r.normal_text) || t("catalog.noLimits")}</bdi>
                  {r.critical_low !== null || r.critical_high !== null ? (
                    <span className="text-xs text-danger-fg">
                      {t("catalog.critical")}:{" "}
                      <bdi dir="ltr">
                        {[r.critical_low ? `≤ ${r.critical_low}` : "", r.critical_high ? `≥ ${r.critical_high}` : ""]
                          .filter(Boolean)
                          .join(" · ")}
                      </bdi>
                    </span>
                  ) : null}
                  <span className="ms-auto flex gap-1">
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={t("catalog.editRange")}
                      onClick={() => {
                        setRangeFor({ parameter: p, range: r });
                      }}
                    >
                      <Pencil aria-hidden="true" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon-sm"
                      aria-label={t("catalog.deleteRange")}
                      onClick={() => {
                        setDeleting(r);
                      }}
                    >
                      <Trash2 aria-hidden="true" />
                    </Button>
                  </span>
                </li>
              ))}
            </ul>
            <div>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setRangeFor({ parameter: p, range: null });
                }}
                data-testid="add-range"
              >
                <Plus aria-hidden="true" />
                {t("catalog.addRange")}
              </Button>
            </div>
          </li>
        ))}
      </ul>
      <ParameterDialog
        testId={test.id}
        parameter={editing}
        open={adding || editing !== null}
        onOpenChange={(o) => {
          if (!o) {
            setAdding(false);
            setEditing(null);
          }
        }}
      />
      <RangeDialog
        parameter={rangeFor?.parameter ?? null}
        range={rangeFor?.range ?? null}
        open={rangeFor !== null}
        onOpenChange={(o) => {
          if (!o) setRangeFor(null);
        }}
      />
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(o) => {
          if (!o) setDeleting(null);
        }}
        title={t("catalog.deleteRangeTitle")}
        description={t("catalog.deleteRangeDescription")}
        confirmLabel={t("catalog.deleteRange")}
        destructive
        onConfirm={async () => {
          if (deleting) await del.mutateAsync(deleting.id);
        }}
      />
    </section>
  );
}
