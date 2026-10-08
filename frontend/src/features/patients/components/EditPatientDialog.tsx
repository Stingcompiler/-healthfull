import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { AlertCard } from "@/components/AlertCard";
import { Form } from "@/components/form";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { toApiError } from "@/lib/api/errors";
import { useTranslateError } from "@/lib/api/translate-error";

import { useUpdatePatient } from "../api";
import type { PatientFile } from "../types";
import { patientFormFrom, patientFormSchema, toPatientPatch, type PatientFormValues } from "../patient-form";
import { PatientFormFields } from "./PatientFormFields";

export interface EditPatientDialogProps {
  patient: PatientFile;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** Edit demographics; also completes an emergency file (FEATURES 1.2). */
export function EditPatientDialog({ patient, open, onOpenChange }: EditPatientDialogProps) {
  const { t } = useTranslation("patients");
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{patient.is_incomplete ? t("edit.completeTitle") : t("edit.title")}</DialogTitle>
          <DialogDescription>
            {patient.is_incomplete ? t("edit.completeDescription") : t("edit.description")}
          </DialogDescription>
        </DialogHeader>
        <EditForm patient={patient} onOpenChange={onOpenChange} />
      </DialogContent>
    </Dialog>
  );
}

/** Mounted only while the dialog is open, so it always starts from the saved file. */
function EditForm({ patient, onOpenChange }: Omit<EditPatientDialogProps, "open">) {
  const { t } = useTranslation(["patients", "common", "errors"]);
  const translateError = useTranslateError();
  const update = useUpdatePatient(patient.id);
  const [error, setError] = useState<string | null>(null);
  const form = useForm<PatientFormValues>({
    resolver: zodResolver(patientFormSchema),
    defaultValues: patientFormFrom(patient),
  });

  const submit = form.handleSubmit(async (values) => {
    setError(null);
    try {
      const saved = await update.mutateAsync(toPatientPatch(values));
      toast.success(patient.is_incomplete && !saved.is_incomplete ? t("edit.completed") : t("edit.saved"));
      onOpenChange(false);
    } catch (e) {
      setError(translateError(toApiError(e)));
    }
  });

  return (
    <Form {...form}>
      <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4">
        <PatientFormFields form={form} allowUnknownSex={patient.sex === "unknown"} />
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
          <Button type="submit" loading={update.isPending}>
            {t("common:actions.save")}
          </Button>
        </DialogFooter>
      </form>
    </Form>
  );
}
