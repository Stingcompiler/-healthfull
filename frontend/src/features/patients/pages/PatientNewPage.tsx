import { zodResolver } from "@hookform/resolvers/zod";
import { Link, useNavigate } from "@tanstack/react-router";
import { UserPlus } from "lucide-react";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { AlertCard } from "@/components/AlertCard";
import { Form } from "@/components/form";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { toApiError } from "@/lib/api/errors";
import { useTranslateError } from "@/lib/api/translate-error";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";

import { useCreatePatient, useDuplicates } from "../api";
import { DuplicateDialog } from "../components/DuplicateDialog";
import { PatientFormFields } from "../components/PatientFormFields";
import { emptyPatientForm, patientFormSchema, toPatientInput, type PatientFormValues } from "../patient-form";
import type { DuplicateQuery } from "../types";

/** Register a patient file (FEATURES 1.1) with the live duplicate warning (1.3). */
export function PatientNewPage() {
  const { t } = useTranslation(["patients", "common", "errors"]);
  const navigate = useNavigate();
  const translateError = useTranslateError();
  const create = useCreatePatient();
  const [error, setError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  const form = useForm<PatientFormValues>({
    resolver: zodResolver(patientFormSchema),
    defaultValues: emptyPatientForm,
  });

  const [nameAr, nameEn, phone, phoneAlt, dobMode, dob, nationalId] = useWatch({
    control: form.control,
    name: ["full_name_ar", "full_name_en", "phone", "phone_alt", "dob_mode", "date_of_birth", "national_id"],
  });
  // Debounce a string (a fresh object every render would restart the timer forever).
  const typed = JSON.stringify({
    full_name_ar: nameAr.trim(),
    full_name_en: nameEn.trim(),
    phone: phone.trim(),
    phone_alt: phoneAlt.trim(),
    date_of_birth: dobMode === "date" && dob ? dob : null,
    national_id: nationalId.trim(),
  } satisfies DuplicateQuery);
  const query = JSON.parse(useDebouncedValue(typed, 400)) as Required<DuplicateQuery>;
  const worthChecking =
    query.phone.length >= 6 ||
    query.phone_alt.length >= 6 ||
    query.national_id !== "" ||
    (Boolean(query.date_of_birth) && (query.full_name_ar !== "" || query.full_name_en !== ""));
  const duplicates = useDuplicates(query, worthChecking);
  const candidates = worthChecking ? (duplicates.data ?? []) : [];

  const register = async (values: PatientFormValues, confirm: boolean) => {
    setError(null);
    try {
      const created = await create.mutateAsync(toPatientInput(values, confirm));
      toast.success(t("new.created", { fileNo: created.file_no }));
      setDialogOpen(false);
      await navigate({ to: "/patients/$patientId", params: { patientId: String(created.id) } });
    } catch (e) {
      const apiError = toApiError(e);
      if (apiError.code === "DUPLICATE_PATIENT") {
        await duplicates.refetch();
        setDialogOpen(true);
        return;
      }
      setDialogOpen(false);
      setError(translateError(apiError));
    }
  };

  const submit = form.handleSubmit(async (values) => {
    if (candidates.length > 0) {
      setDialogOpen(true);
      return;
    }
    await register(values, false);
  });

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        icon={<UserPlus />}
        eyebrow={<Link to="/patients">{t("title")}</Link>}
        title={t("new.title")}
        description={t("new.description")}
      />
      <Form {...form}>
        <form onSubmit={(e) => void submit(e)} noValidate className="card-surface grid gap-5 p-4 md:p-5">
          <PatientFormFields form={form} />
          {candidates.length > 0 ? (
            <AlertCard
              variant="warning"
              title={t("duplicates.inlineTitle", { count: candidates.length })}
              live
              action={
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setDialogOpen(true);
                  }}
                >
                  {t("duplicates.review")}
                </Button>
              }
            >
              {t("duplicates.inlineDescription")}
            </AlertCard>
          ) : null}
          {error ? (
            <AlertCard variant="danger" title={t("errors:title")} live>
              {error}
            </AlertCard>
          ) : null}
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button asChild variant="outline">
              <Link to="/patients">{t("common:actions.cancel")}</Link>
            </Button>
            <Button type="submit" loading={create.isPending}>
              {t("new.submit")}
            </Button>
          </div>
        </form>
      </Form>
      <DuplicateDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        candidates={duplicates.data ?? []}
        pending={create.isPending}
        onConfirm={() => {
          void form.handleSubmit((values) => register(values, true))();
        }}
      />
    </div>
  );
}
