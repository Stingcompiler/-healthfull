import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { AlertCard } from "@/components/AlertCard";
import { Form, SelectField, TextareaField, TextField } from "@/components/form";
import { MoneyText } from "@/components/MoneyText";
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

import { useReasons, useRequestRefund } from "../api";
import { isAmount, isPositiveAmount, normalizeAmountInput } from "../lib/money";
import { useNames } from "../lib/use-names";
import type { CreditNote } from "../types";

const schema = z.object({
  amount: z
    .string()
    .trim()
    .min(1, vmsg("validation.required"))
    .refine((v) => isAmount(v) && isPositiveAmount(v), vmsg("cashier:validation.positiveAmount")),
  reason: z.string().min(1, vmsg("validation.selectOption")),
  note: z.string().trim().max(1000),
});

type Values = z.infer<typeof schema>;

/** Mounted only while open, so every opening starts with a fresh form. */
export function RefundRequestDialog(props: Parameters<typeof RefundRequestDialogOpen>[0]) {
  return props.creditNote !== null ? <RefundRequestDialogOpen {...props} /> : null;
}

/** Request a cash refund of the credit an approved credit note created (FEATURES 6.7). */
function RefundRequestDialogOpen({
  creditNote,
  onOpenChange,
}: {
  creditNote: CreditNote | null;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation(["cashier", "common", "errors"]);
  const translateError = useTranslateError();
  const names = useNames();
  const open = creditNote !== null;
  const reasons = useReasons("refund", open);
  const request = useRequestRefund();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { amount: creditNote?.refundable ?? "", reason: "", note: "" },
  });

  const submit = form.handleSubmit(async (v) => {
    if (!creditNote) return;
    setError(null);
    try {
      await request.mutateAsync({
        credit_note_id: creditNote.id,
        amount: normalizeAmountInput(v.amount),
        reason: v.reason,
        note: v.note,
      });
      onOpenChange(false);
    } catch (e) {
      setError(translateError(e));
    }
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("refunds.requestTitle")}</DialogTitle>
          <DialogDescription>{t("refunds.requestDescription")}</DialogDescription>
        </DialogHeader>
        {creditNote ? (
          <p className="flex flex-wrap items-center justify-between gap-2 rounded-control bg-subtle px-3 py-2 text-sm">
            <bdi>{creditNote.number}</bdi>
            <span>
              {t("creditNotes.refundable")} <MoneyText value={creditNote.refundable} />
            </span>
          </p>
        ) : null}
        <Form {...form}>
          <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4">
            <TextField
              control={form.control}
              name="amount"
              label={t("refunds.amount")}
              inputMode="decimal"
              dir="ltr"
              required
            />
            <SelectField
              control={form.control}
              name="reason"
              label={t("common:reason.code")}
              placeholder={t("common:reason.codePlaceholder")}
              options={(reasons.data ?? []).map((r) => ({ value: r.code, label: names.label(r) }))}
              required
            />
            <TextareaField control={form.control} name="note" label={t("common:reason.note")} rows={2} />
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
              <Button type="submit" loading={form.formState.isSubmitting}>
                {t("refunds.request")}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
