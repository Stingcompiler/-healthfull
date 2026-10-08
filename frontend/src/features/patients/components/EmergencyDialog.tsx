import { zodResolver } from "@hookform/resolvers/zod";
import { useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { z } from "zod";

import { AlertCard } from "@/components/AlertCard";
import { Form, RadioGroupField, TextField } from "@/components/form";
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
import { requiredString, vmsg } from "@/lib/validation";

import { useRegisterEmergency } from "../api";

const schema = z.object({
  name: requiredString.max(200),
  sex: z.enum(["male", "female", "unknown"]),
  age_years: z
    .string()
    .trim()
    .refine((v) => v === "" || /^\d{1,3}$/.test(v), vmsg("validation.number")),
  phone: z
    .string()
    .trim()
    .refine((v) => v === "" || /^0\d{9}$/.test(v), vmsg("validation.phone")),
});
type Values = z.infer<typeof schema>;
const EMPTY: Values = { name: "", sex: "unknown", age_years: "", phone: "" };

export interface EmergencyDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** Emergency registration with a name (or placeholder) and sex only (FEATURES 1.2). */
export function EmergencyDialog({ open, onOpenChange }: EmergencyDialogProps) {
  const { t } = useTranslation("patients");
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("emergency.title")}</DialogTitle>
          <DialogDescription>{t("emergency.description")}</DialogDescription>
        </DialogHeader>
        <EmergencyForm onOpenChange={onOpenChange} />
      </DialogContent>
    </Dialog>
  );
}

/** Mounted only while the dialog is open, so every opening starts from an empty form. */
function EmergencyForm({ onOpenChange }: { onOpenChange: (open: boolean) => void }) {
  const { t } = useTranslation(["patients", "common", "errors"]);
  const navigate = useNavigate();
  const translateError = useTranslateError();
  const register = useRegisterEmergency();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: EMPTY });

  const submit = form.handleSubmit(async (values) => {
    setError(null);
    try {
      const created = await register.mutateAsync({
        name: values.name,
        sex: values.sex,
        age_years: values.age_years === "" ? null : Number(values.age_years),
        phone: values.phone,
      });
      toast.success(t("emergency.created", { fileNo: created.file_no }));
      onOpenChange(false);
      await navigate({ to: "/patients/$patientId", params: { patientId: String(created.id) } });
    } catch (e) {
      setError(translateError(toApiError(e)));
    }
  });

  return (
    <Form {...form}>
      <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4">
        <TextField
          control={form.control}
          name="name"
          label={t("emergency.name")}
          description={t("emergency.nameHint")}
          required
          autoFocus
        />
        <RadioGroupField
          control={form.control}
          name="sex"
          label={t("form.sex")}
          required
          options={[
            { value: "male", label: t("common:sex.male") },
            { value: "female", label: t("common:sex.female") },
            { value: "unknown", label: t("common:sex.unknown") },
          ]}
        />
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField
            control={form.control}
            name="age_years"
            label={t("form.ageYears")}
            inputMode="numeric"
            dir="ltr"
            maxLength={3}
          />
          <TextField control={form.control} name="phone" label={t("form.phone")} type="tel" dir="ltr" />
        </div>
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
          <Button type="submit" variant="destructive" loading={register.isPending}>
            {t("emergency.submit")}
          </Button>
        </DialogFooter>
      </form>
    </Form>
  );
}
