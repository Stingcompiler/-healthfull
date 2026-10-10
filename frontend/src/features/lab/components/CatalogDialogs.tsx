import { zodResolver } from "@hookform/resolvers/zod";
import { useState, type ReactNode } from "react";
import { useForm, useWatch } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { AlertCard } from "@/components/AlertCard";
import { Form, SelectField, SwitchField, TextField } from "@/components/form";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useTranslateError } from "@/lib/api/translate-error";
import { vmsg } from "@/lib/validation";

import { useCreateParameter, useSaveRange, useUpdateParameter } from "../api";
import { splitDays, toDays } from "../lib/ages";
import { RANGE_SEXES, VALUE_TYPES, type LabParameter, type LabRange, type RangeSex, type ValueType } from "../types";

const DECIMAL = /^-?[0-9]{1,10}(\.[0-9]{1,4})?$/;
const optionalDecimal = z
  .string()
  .trim()
  .refine((v) => v === "" || DECIMAL.test(v), vmsg("validation.number"));
const optionalWhole = z
  .string()
  .trim()
  .refine((v) => v === "" || /^[0-9]{1,5}(\.[0-9]{1,2})?$/.test(v), vmsg("validation.number"));

function DialogShell({
  open,
  onOpenChange,
  title,
  description,
  children,
  testId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description: ReactNode;
  children: ReactNode;
  testId: string;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid={testId}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        {open ? children : null}
      </DialogContent>
    </Dialog>
  );
}

function Footer({
  onCancel,
  pending,
  label,
  error,
}: {
  onCancel: () => void;
  pending: boolean;
  label: string;
  error: string | null;
}) {
  const { t } = useTranslation(["common", "errors"]);
  return (
    <>
      {error ? (
        <AlertCard variant="danger" title={t("errors:title")} live>
          {error}
        </AlertCard>
      ) : null}
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onCancel}>
          {t("actions.cancel")}
        </Button>
        <Button type="submit" loading={pending} data-testid="dialog-save">
          {label}
        </Button>
      </DialogFooter>
    </>
  );
}

// --- parameter -------------------------------------------------------------------------------

const parameterSchema = z.object({
  code: z
    .string()
    .trim()
    .min(1, vmsg("validation.required"))
    .max(30)
    .regex(/^[A-Za-z0-9_-]+$/, vmsg("validation.invalid")),
  name_ar: z.string().trim().min(1, vmsg("validation.required")).max(150),
  name_en: z.string().trim().min(1, vmsg("validation.required")).max(150),
  unit: z.string().trim().max(30),
  value_type: z.string().min(1, vmsg("validation.selectOption")),
  choices: z.string().max(1000),
  decimals: z.string().regex(/^[0-6]$/, vmsg("validation.number")),
  sort_order: z.string().regex(/^[0-9]{1,4}$/, vmsg("validation.number")),
  active: z.boolean(),
});
type ParameterValues = z.infer<typeof parameterSchema>;

/** Add a parameter to a test, or edit one (its code is fixed once created). */
export function ParameterDialog({
  testId,
  parameter,
  open,
  onOpenChange,
}: {
  testId: number;
  parameter: LabParameter | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation("lab");
  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      title={parameter ? t("catalog.editParameter") : t("catalog.addParameter")}
      description={t("catalog.parameterDescription")}
      testId="parameter-dialog"
    >
      <ParameterForm
        testId={testId}
        parameter={parameter}
        onDone={() => {
          onOpenChange(false);
        }}
      />
    </DialogShell>
  );
}

function ParameterForm({
  testId,
  parameter,
  onDone,
}: {
  testId: number;
  parameter: LabParameter | null;
  onDone: () => void;
}) {
  const { t } = useTranslation(["lab", "common"]);
  const translateError = useTranslateError();
  const create = useCreateParameter(testId);
  const update = useUpdateParameter();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<ParameterValues>({
    resolver: zodResolver(parameterSchema),
    defaultValues: {
      code: parameter?.code ?? "",
      name_ar: parameter?.name_ar ?? "",
      name_en: parameter?.name_en ?? "",
      unit: parameter?.unit ?? "",
      value_type: parameter?.value_type ?? "numeric",
      choices: (parameter?.choices ?? []).join("\n"),
      decimals: String(parameter?.decimals ?? 1),
      sort_order: String(parameter?.sort_order ?? 0),
      active: parameter?.active ?? true,
    },
  });
  const valueType = useWatch({ control: form.control, name: "value_type" });
  const submit = form.handleSubmit(async (v) => {
    setError(null);
    const choices = v.choices
      .split(/[\n,،]/)
      .map((c) => c.trim())
      .filter(Boolean);
    const body = {
      name_ar: v.name_ar,
      name_en: v.name_en,
      unit: v.unit,
      value_type: v.value_type as ValueType,
      choices,
      decimals: Number(v.decimals),
      sort_order: Number(v.sort_order),
    };
    try {
      if (parameter) await update.mutateAsync({ parameterId: parameter.id, body: { ...body, active: v.active } });
      else await create.mutateAsync({ ...body, code: v.code.toUpperCase() });
      onDone();
    } catch (e) {
      setError(translateError(e));
    }
  });
  return (
    <Form {...form}>
      <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField
            control={form.control}
            name="code"
            label={t("catalog.code")}
            dir="ltr"
            disabled={parameter !== null}
            required
          />
          <TextField control={form.control} name="unit" label={t("catalog.unit")} dir="ltr" maxLength={30} />
          <TextField control={form.control} name="name_ar" label={t("catalog.nameAr")} dir="rtl" required />
          <TextField control={form.control} name="name_en" label={t("catalog.nameEn")} dir="ltr" required />
          <SelectField
            control={form.control}
            name="value_type"
            label={t("catalog.valueType")}
            options={VALUE_TYPES.map((v) => ({ value: v, label: t(`valueType.${v}`) }))}
            required
          />
          <TextField
            control={form.control}
            name="decimals"
            label={t("catalog.decimals")}
            type="number"
            inputMode="numeric"
            dir="ltr"
          />
          <TextField
            control={form.control}
            name="sort_order"
            label={t("catalog.sortOrder")}
            type="number"
            inputMode="numeric"
            dir="ltr"
          />
        </div>
        {valueType === "choice" ? (
          <TextField
            control={form.control}
            name="choices"
            label={t("catalog.choices")}
            description={t("catalog.choicesHint")}
            dir="ltr"
            required
          />
        ) : null}
        {parameter ? <SwitchField control={form.control} name="active" label={t("catalog.parameterActive")} /> : null}
        <Footer
          onCancel={onDone}
          pending={form.formState.isSubmitting}
          label={t("common:actions.save")}
          error={error}
        />
      </form>
    </Form>
  );
}

// --- reference range -------------------------------------------------------------------------

const rangeSchema = z.object({
  sex: z.string().min(1),
  age_min: optionalWhole,
  age_min_unit: z.enum(["days", "years"]),
  age_max: optionalWhole,
  age_max_unit: z.enum(["days", "years"]),
  low: optionalDecimal,
  high: optionalDecimal,
  critical_low: optionalDecimal,
  critical_high: optionalDecimal,
  normal_text: z.string().trim().max(100),
  note: z.string().trim().max(200),
});
type RangeValues = z.infer<typeof rangeSchema>;

/** Add or replace a reference range: sex, age band, normal and critical limits. */
export function RangeDialog({
  parameter,
  range,
  open,
  onOpenChange,
}: {
  parameter: LabParameter | null;
  range: LabRange | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation("lab");
  return (
    <DialogShell
      open={open}
      onOpenChange={onOpenChange}
      title={range ? t("catalog.editRange") : t("catalog.addRange")}
      description={t("catalog.rangeDescription")}
      testId="range-dialog"
    >
      {parameter ? (
        <RangeForm
          parameter={parameter}
          range={range}
          onDone={() => {
            onOpenChange(false);
          }}
        />
      ) : null}
    </DialogShell>
  );
}

function RangeForm({
  parameter,
  range,
  onDone,
}: {
  parameter: LabParameter;
  range: LabRange | null;
  onDone: () => void;
}) {
  const { t } = useTranslation(["lab", "common"]);
  const translateError = useTranslateError();
  const save = useSaveRange();
  const [error, setError] = useState<string | null>(null);
  const min = splitDays(range ? range.age_min_days : null);
  const max = splitDays(range?.age_max_days ?? null);
  const form = useForm<RangeValues>({
    resolver: zodResolver(rangeSchema),
    defaultValues: {
      sex: range?.sex ?? "any",
      age_min: range && range.age_min_days > 0 ? min.value : "",
      age_min_unit: min.unit,
      age_max: max.value,
      age_max_unit: max.unit,
      low: range?.low ?? "",
      high: range?.high ?? "",
      critical_low: range?.critical_low ?? "",
      critical_high: range?.critical_high ?? "",
      normal_text: range?.normal_text ?? "",
      note: range?.note ?? "",
    },
  });
  const numeric = parameter.value_type === "numeric";
  const unitOptions = (["years", "days"] as const).map((u) => ({ value: u, label: t(`catalog.ageUnit.${u}`) }));
  const submit = form.handleSubmit(async (v) => {
    setError(null);
    const value = (s: string) => (s.trim() === "" ? null : s.trim());
    try {
      await save.mutateAsync({
        parameterId: parameter.id,
        rangeId: range?.id ?? null,
        body: {
          sex: v.sex as RangeSex,
          age_min_days: toDays(v.age_min, v.age_min_unit) ?? 0,
          age_max_days: toDays(v.age_max, v.age_max_unit),
          low: numeric ? value(v.low) : null,
          high: numeric ? value(v.high) : null,
          critical_low: numeric ? value(v.critical_low) : null,
          critical_high: numeric ? value(v.critical_high) : null,
          normal_text: v.normal_text,
          note: v.note,
        },
      });
      onDone();
    } catch (e) {
      setError(translateError(e));
    }
  });
  return (
    <Form {...form}>
      <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4">
        <SelectField
          control={form.control}
          name="sex"
          label={t("catalog.rangeSex")}
          options={RANGE_SEXES.map((s) => ({ value: s, label: t(`sex.${s}`) }))}
        />
        <div className="grid grid-cols-2 gap-3">
          <TextField
            control={form.control}
            name="age_min"
            label={t("catalog.ageFrom")}
            type="text"
            inputMode="decimal"
            dir="ltr"
          />
          <SelectField
            control={form.control}
            name="age_min_unit"
            label={t("catalog.ageUnitLabel")}
            options={unitOptions}
          />
          <TextField
            control={form.control}
            name="age_max"
            label={t("catalog.ageTo")}
            type="text"
            inputMode="decimal"
            dir="ltr"
          />
          <SelectField
            control={form.control}
            name="age_max_unit"
            label={t("catalog.ageUnitLabel")}
            options={unitOptions}
          />
        </div>
        {numeric ? (
          <div className="grid grid-cols-2 gap-3">
            <TextField control={form.control} name="low" label={t("catalog.low")} inputMode="decimal" dir="ltr" />
            <TextField control={form.control} name="high" label={t("catalog.high")} inputMode="decimal" dir="ltr" />
            <TextField
              control={form.control}
              name="critical_low"
              label={t("catalog.criticalLow")}
              inputMode="decimal"
              dir="ltr"
            />
            <TextField
              control={form.control}
              name="critical_high"
              label={t("catalog.criticalHigh")}
              inputMode="decimal"
              dir="ltr"
            />
          </div>
        ) : (
          <TextField control={form.control} name="normal_text" label={t("catalog.normalText")} dir="ltr" />
        )}
        <TextField control={form.control} name="note" label={t("catalog.note")} maxLength={200} />
        <Footer
          onCancel={onDone}
          pending={form.formState.isSubmitting}
          label={t("common:actions.save")}
          error={error}
        />
      </form>
    </Form>
  );
}
