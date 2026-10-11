import { zodResolver } from "@hookform/resolvers/zod";
import { Link } from "@tanstack/react-router";
import { Ban } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { z } from "zod";

import { AlertCard } from "@/components/AlertCard";
import { Form, SelectField, TextareaField } from "@/components/form";
import { SecondApproverFields } from "@/components/SecondApproverFields";
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
import { reasonLabel, useReasonCodes } from "@/lib/api/use-reason-codes";
import { usePermission } from "@/lib/auth/hooks";
import { useLanguage } from "@/lib/i18n-hooks";
import { vmsg } from "@/lib/validation";

import { useCancelAdmission } from "../api";
import { patientName } from "../lib";
import type { OccupiedBed } from "./BedActionDialogs";

const schema = z.object({
  reason: z.string().min(1, vmsg("validation.selectOption")),
  note: z.string().trim().max(500),
  username: z.string().trim().min(1, vmsg("validation.required")),
  password: z.string().min(1, vmsg("validation.required")),
});

type Values = z.infer<typeof schema>;

/**
 * An admission made in error (ADR 0018): cancelled with a reason and a second person's
 * approval. The bed is freed and the nights not yet invoiced are voided; invoiced nights are
 * credited at the cashier first, so the dialog says so instead of offering the form.
 */
export function CancelAdmissionDialog({
  target,
  onOpenChange,
}: {
  target: OccupiedBed | null;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation("nursing");
  const language = useLanguage();
  const name = target ? patientName(target.occupant.patient, language) : "";
  return (
    <Dialog
      open={target !== null}
      onOpenChange={(open) => {
        if (!open) onOpenChange(false);
      }}
    >
      <DialogContent className="sm:max-w-lg" data-testid="cancel-admission-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Ban className="size-5 text-danger" aria-hidden="true" />
            {t("cancelAdmission.title")}
          </DialogTitle>
          {target ? (
            <DialogDescription>{t("cancelAdmission.description", { name, bed: target.bed.code })}</DialogDescription>
          ) : null}
        </DialogHeader>
        {target ? <CancelForm target={target} name={name} onDone={() => onOpenChange(false)} /> : null}
      </DialogContent>
    </Dialog>
  );
}

function CancelForm({ target, name, onDone }: { target: OccupiedBed; name: string; onDone: () => void }) {
  const { t } = useTranslation(["nursing", "common", "errors"]);
  const language = useLanguage();
  const translateError = useTranslateError();
  const reasons = useReasonCodes("admission_cancel");
  const cancel = useCancelAdmission();
  const canOpenCashier = usePermission("billing.view");
  const [error, setError] = useState<string | null>(null);
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { reason: "", note: "", username: "", password: "" },
  });
  const occupant = target.occupant;
  const invoiced = occupant.nights_invoiced;
  const unbilled = Math.max(occupant.nights_charged - invoiced, 0);

  if (invoiced > 0) {
    return (
      <div className="grid gap-4">
        <AlertCard variant="warning" title={t("cancelAdmission.invoicedTitle", { count: invoiced })} live>
          {t("cancelAdmission.invoicedBody")}
        </AlertCard>
        <DialogFooter>
          {canOpenCashier ? (
            <Button variant="outline" asChild>
              <Link to="/cashier" search={{ visit: occupant.visit_id }}>
                {t("cancelAdmission.openCashier")}
              </Link>
            </Button>
          ) : null}
          <Button type="button" onClick={onDone}>
            {t("common:actions.close")}
          </Button>
        </DialogFooter>
      </div>
    );
  }

  const submit = form.handleSubmit(async (v) => {
    setError(null);
    try {
      await cancel.mutateAsync({
        admissionId: occupant.admission_id,
        body: {
          reason_code: v.reason,
          note: v.note.trim(),
          approver: { username: v.username.trim(), password: v.password },
        },
      });
      toast.success(t("cancelAdmission.savedToast", { name }));
      onDone();
    } catch (e) {
      setError(translateError(e));
    }
  });

  return (
    <Form {...form}>
      <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4">
        <AlertCard variant="info" title={t("cancelAdmission.nightsVoided", { count: unbilled })} />
        <SelectField
          control={form.control}
          name="reason"
          label={t("common:reason.code")}
          placeholder={t("common:reason.codePlaceholder")}
          options={(reasons.data ?? []).map((r) => ({ value: r.code, label: reasonLabel(r, language) }))}
          required
        />
        <TextareaField
          control={form.control}
          name="note"
          label={t("common:reason.note")}
          placeholder={t("common:reason.notePlaceholder")}
          rows={2}
          maxLength={500}
        />
        <SecondApproverFields
          control={form.control}
          usernameName="username"
          passwordName="password"
          hint={t("cancelAdmission.approverHint")}
        />
        {error ? (
          <AlertCard variant="danger" title={t("errors:title")} live>
            {error}
          </AlertCard>
        ) : null}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onDone}>
            {t("common:actions.cancel")}
          </Button>
          <Button
            type="submit"
            variant="destructive"
            loading={form.formState.isSubmitting}
            data-testid="cancel-admission-confirm"
          >
            {t("cancelAdmission.confirm")}
          </Button>
        </DialogFooter>
      </form>
    </Form>
  );
}
