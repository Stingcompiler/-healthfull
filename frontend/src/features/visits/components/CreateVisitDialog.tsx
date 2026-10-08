import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { AlertCard } from "@/components/AlertCard";
import { Form, RadioGroupField, SelectField, TextField } from "@/components/form";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { useCoverages } from "@/features/patients/api";
import { PatientPicker } from "@/features/patients/components/PatientPicker";
import type { PatientListItem } from "@/features/patients/types";
import { toApiError } from "@/lib/api/errors";
import { useTranslateError } from "@/lib/api/translate-error";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";
import { vmsg } from "@/lib/validation";

import { useCreateVisit, useVisitOptions } from "../api";
import type { VisitDetail } from "../types";

/** "default" = the default coverage on file, "cash" = self-pay, otherwise a coverage id. */
const NO_DOCTOR = "none";

const schema = z.object({
  department: z.string().min(1, vmsg("validation.selectOption")),
  doctor: z.string(),
  visit_type: z.enum(["new", "follow_up", "emergency"]),
  coverage: z.string(),
  card_number: z.string().trim().max(60),
  chief_complaint: z.string().trim().max(300),
});
type Values = z.infer<typeof schema>;

export interface CreateVisitDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Preselected patient (from the patient file); otherwise the dialog searches. */
  patient?: PatientListItem | null;
  defaultDepartmentId?: number | null;
  onCreated?: (visit: VisitDetail) => void;
}

/** Open a visit: department, doctor, coverage and type (FEATURES 2.1). The fee line is automatic. */
export function CreateVisitDialog(props: CreateVisitDialogProps) {
  // Mounted only while open, so each visit starts from the defaults.
  return props.open ? <CreateVisitBody {...props} /> : null;
}

function CreateVisitBody({
  open,
  onOpenChange,
  patient: presetPatient = null,
  defaultDepartmentId = null,
  onCreated,
}: CreateVisitDialogProps) {
  const { t } = useTranslation(["visits", "common", "errors"]);
  const language = useLanguage();
  const translateError = useTranslateError();
  const options = useVisitOptions();
  const create = useCreateVisit();
  const [patient, setPatient] = useState<PatientListItem | null>(presetPatient);
  const [error, setError] = useState<string | null>(null);
  const coverages = useCoverages(patient?.id ?? 0, false, patient !== null);
  const defaults: Values = {
    department: defaultDepartmentId ? String(defaultDepartmentId) : "",
    doctor: NO_DOCTOR,
    visit_type: "new",
    coverage: "default",
    card_number: "",
    chief_complaint: "",
  };
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: defaults });
  const { setValue } = form;
  const department = useWatch({ control: form.control, name: "department" });
  const doctor = useWatch({ control: form.control, name: "doctor" });

  // Choosing a doctor selects the doctor's clinic.
  useEffect(() => {
    if (doctor === NO_DOCTOR) return;
    const found = options.data?.doctors.find((d) => String(d.id) === doctor);
    if (found && String(found.department_id) !== department) setValue("department", String(found.department_id));
  }, [doctor, department, options.data, setValue]);

  const departments = options.data?.departments ?? [];
  const doctors = (options.data?.doctors ?? []).filter((d) => !department || String(d.department_id) === department);
  const fileCoverages = patient ? (coverages.data ?? []) : [];

  const submit = form.handleSubmit(async (values) => {
    if (!patient) {
      setError(t("create.patientRequired"));
      return;
    }
    setError(null);
    const coverageId = values.coverage === "default" || values.coverage === "cash" ? null : Number(values.coverage);
    try {
      const created = await create.mutateAsync({
        patient_id: patient.id,
        department_id: Number(values.department),
        doctor_id: values.doctor === NO_DOCTOR ? null : Number(values.doctor),
        visit_type: values.visit_type,
        coverage_id: coverageId,
        use_default_coverage: values.coverage === "default",
        card_number: values.card_number,
        chief_complaint: values.chief_complaint,
      });
      onOpenChange(false);
      onCreated?.(created);
    } catch (e) {
      setError(translateError(toApiError(e)));
    }
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>{t("create.title")}</DialogTitle>
          <DialogDescription>{t("create.description")}</DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4">
            <div className="grid gap-2">
              <Label>{t("create.patient")}</Label>
              {presetPatient ? (
                <PatientPicker value={patient} onChange={setPatient} readOnly />
              ) : (
                <PatientPicker value={patient} onChange={setPatient} autoFocus />
              )}
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <SelectField
                control={form.control}
                name="department"
                label={t("create.department")}
                placeholder={t("create.departmentPlaceholder")}
                required
                options={departments.map((d) => ({
                  value: String(d.id),
                  label: pickName({ ar: d.name_ar, en: d.name_en }, language),
                }))}
              />
              <SelectField
                control={form.control}
                name="doctor"
                label={t("create.doctor")}
                options={[
                  { value: NO_DOCTOR, label: t("create.noDoctor") },
                  ...doctors.map((d) => ({
                    value: String(d.id),
                    label: pickName({ ar: d.name_ar, en: d.name_en }, language),
                  })),
                ]}
              />
            </div>
            <RadioGroupField
              control={form.control}
              name="visit_type"
              label={t("create.type")}
              options={[
                { value: "new", label: t("visitType.new") },
                { value: "follow_up", label: t("visitType.follow_up") },
                { value: "emergency", label: t("visitType.emergency") },
              ]}
            />
            <div className="grid gap-4 sm:grid-cols-2">
              <SelectField
                control={form.control}
                name="coverage"
                label={t("create.coverage")}
                options={[
                  { value: "default", label: t("create.coverageDefault") },
                  { value: "cash", label: t("create.coverageCash") },
                  ...fileCoverages.map((c) => ({
                    value: String(c.id),
                    label: [pickName({ ar: c.payer.name_ar, en: c.payer.name_en }, language), c.card_number]
                      .filter(Boolean)
                      .join(" · "),
                  })),
                ]}
              />
              <TextField control={form.control} name="card_number" label={t("create.cardNumber")} dir="ltr" />
            </div>
            <TextField control={form.control} name="chief_complaint" label={t("create.complaint")} />
            <p className="text-xs text-muted">
              {t("create.feeHint", { days: options.data?.follow_up_window_days ?? 0 })}
            </p>
            {error ? (
              <AlertCard variant="danger" title={t("errors:title")} live>
                {error}
              </AlertCard>
            ) : null}
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  onOpenChange(false);
                }}
              >
                {t("common:actions.cancel")}
              </Button>
              <Button type="submit" loading={create.isPending}>
                {t("create.submit")}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
