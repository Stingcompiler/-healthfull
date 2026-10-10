import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { AlertCard } from "@/components/AlertCard";
import { Form, PasswordField, SelectField, TextareaField, TextField } from "@/components/form";
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
import { usePermission } from "@/lib/auth/hooks";
import { vmsg } from "@/lib/validation";

import { useCancelTest, useLabReasons } from "../api";
import { useLabNames } from "../lib/use-lab-names";
import type { LabResult } from "../types";

/** The cancellation reasons a lab uses (a test the doctor withdrew is not cancelled here). */
const LAB_REASONS = new Set(["SAMPLE_UNUSABLE", "EQUIPMENT_DOWN", "PATIENT_REFUSED", "OTHER"]);

function schema(needsApprover: boolean) {
  const credential = needsApprover ? z.string().trim().min(1, vmsg("validation.required")) : z.string().trim();
  return z.object({
    reason: z.string().min(1, vmsg("validation.selectOption")),
    note: z.string().trim().max(500),
    username: credential,
    password: needsApprover ? z.string().min(1, vmsg("validation.required")) : z.string(),
  });
}

type Values = z.infer<ReturnType<typeof schema>>;

/**
 * The test cannot be performed (FEATURES 9.7): cancelled with a reason. A billed test is
 * credited, which needs a cashier supervisor's or accountant's approval typed in here
 * (ADR 0009); the patient's money becomes credit and a refund request opens at the cashier.
 */
export function CancelTestDialog({
  result,
  open,
  onOpenChange,
}: {
  result: LabResult;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation(["lab", "common", "errors"]);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="cancel-test-dialog">
        <DialogHeader>
          <DialogTitle>{t("cancel.title")}</DialogTitle>
          <DialogDescription>{t("cancel.description")}</DialogDescription>
        </DialogHeader>
        {open ? <CancelForm result={result} onOpenChange={onOpenChange} /> : null}
      </DialogContent>
    </Dialog>
  );
}

function CancelForm({ result, onOpenChange }: { result: LabResult; onOpenChange: (open: boolean) => void }) {
  const { t } = useTranslation(["lab", "common", "errors"]);
  const names = useLabNames();
  const translateError = useTranslateError();
  const reasons = useLabReasons("line_cancel");
  const cancel = useCancelTest(result.line.id);
  const billed = result.line.billing_status === "invoiced" || result.line.billing_status === "settled";
  const canCredit = usePermission("billing.approve_credit_note");
  const needsApprover = billed && !canCredit;
  const [error, setError] = useState<string | null>(null);
  const form = useForm<Values>({
    resolver: zodResolver(schema(needsApprover)),
    defaultValues: { reason: "", note: "", username: "", password: "" },
  });

  const options = (reasons.data ?? [])
    .filter((r) => LAB_REASONS.has(r.code))
    .map((r) => ({ value: r.code, label: names.reason(r) }));

  const submit = form.handleSubmit(async (v) => {
    setError(null);
    try {
      await cancel.mutateAsync({
        reason: v.reason,
        note: v.note.trim(),
        approver: v.username.trim() ? { username: v.username.trim(), password: v.password } : null,
      });
      onOpenChange(false);
    } catch (e) {
      setError(translateError(e));
    }
  });

  return (
    <Form {...form}>
      <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4">
        <SelectField
          control={form.control}
          name="reason"
          label={t("common:reason.code")}
          placeholder={t("common:reason.codePlaceholder")}
          options={options}
          required
        />
        <TextareaField control={form.control} name="note" label={t("common:reason.note")} rows={2} maxLength={500} />
        {billed ? (
          <fieldset className="grid gap-3 rounded-control border border-border p-3" data-testid="cancel-approver">
            <legend className="px-1 text-sm font-medium">{t("cancel.approverTitle")}</legend>
            <p className="text-xs text-muted">{needsApprover ? t("cancel.approverHint") : t("cancel.approverSelf")}</p>
            <div className="grid gap-3 sm:grid-cols-2">
              <TextField
                control={form.control}
                name="username"
                label={t("cancel.username")}
                autoComplete="off"
                dir="ltr"
                required={needsApprover}
              />
              <PasswordField
                control={form.control}
                name="password"
                label={t("cancel.password")}
                autoComplete="new-password"
                required={needsApprover}
              />
            </div>
          </fieldset>
        ) : null}
        {billed ? <p className="text-xs text-muted">{t("cancel.refundNote")}</p> : null}
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
          <Button
            type="submit"
            variant="destructive"
            loading={form.formState.isSubmitting}
            data-testid="confirm-cancel"
          >
            {t("cancel.confirm")}
          </Button>
        </DialogFooter>
      </form>
    </Form>
  );
}
