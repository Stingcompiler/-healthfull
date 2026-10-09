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
import { compareAmounts, isAmount, isPositiveAmount, normalizeAmountInput } from "@/features/cashier/lib/money";
import { useTranslateError } from "@/lib/api/translate-error";
import { vmsg } from "@/lib/validation";

import { useWriteOffShortfall } from "../api";
import { useClaimNames } from "../lib/names";
import type { ClaimLine, ClaimReason } from "../types";

function schemaFor(unpaid: string) {
  return z.object({
    amount: z
      .string()
      .trim()
      .min(1, vmsg("validation.required"))
      .refine(isAmount, vmsg("claims:validation.amount"))
      .refine(isPositiveAmount, vmsg("claims:validation.positive"))
      .refine((v) => compareAmounts(v, unpaid) !== 1, vmsg("claims:validation.atMostUnpaid")),
    reason: z.string().min(1, vmsg("validation.selectOption")),
    note: z.string().trim().max(500),
  });
}

type Values = z.infer<ReturnType<typeof schemaFor>>;

interface ShortfallDialogProps {
  claimId: number;
  line: ClaimLine | null;
  reasons: readonly ClaimReason[];
  onOpenChange: (open: boolean) => void;
}

/** Mounted only while open, so every write-off starts from a fresh form. */
export function ShortfallDialog(props: ShortfallDialogProps) {
  return props.line ? <ShortfallDialogOpen {...props} line={props.line} /> : null;
}

/**
 * Write off accepted money the payer will not pay (withholding, deductions; FEATURES 11.5),
 * with a reason. The server records approver and time (invariant 4).
 */
function ShortfallDialogOpen({ claimId, line, reasons, onOpenChange }: ShortfallDialogProps & { line: ClaimLine }) {
  const { t } = useTranslation(["claims", "common", "errors"]);
  const translateError = useTranslateError();
  const names = useClaimNames();
  const writeOff = useWriteOffShortfall();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<Values>({
    resolver: zodResolver(schemaFor(line.unpaid)),
    defaultValues: { amount: line.unpaid, reason: "", note: "" },
  });

  const submit = form.handleSubmit(async (v) => {
    setError(null);
    try {
      await writeOff.mutateAsync({
        claimId,
        lineId: line.id,
        body: { amount: normalizeAmountInput(v.amount), reason: v.reason, note: v.note },
      });
      onOpenChange(false);
    } catch (e) {
      setError(translateError(e));
    }
  });

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent data-testid="shortfall-dialog">
        <DialogHeader>
          <DialogTitle>{t("shortfall.title")}</DialogTitle>
          <DialogDescription>{t("shortfall.description")}</DialogDescription>
        </DialogHeader>
        <p className="flex flex-wrap items-center justify-between gap-2 rounded-control bg-subtle px-3 py-2 text-sm">
          <span>{t("detail.unpaid")}</span>
          <MoneyText value={line.unpaid} />
        </p>
        <Form {...form}>
          <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4">
            <TextField
              control={form.control}
              name="amount"
              label={t("shortfall.amount")}
              inputMode="decimal"
              dir="ltr"
              required
            />
            <SelectField
              control={form.control}
              name="reason"
              label={t("resolve.reason")}
              required
              options={reasons.map((r) => ({ value: r.code, label: names.label(r) }))}
            />
            <TextareaField control={form.control} name="note" label={t("resolve.note")} />
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
              <Button type="submit" variant="destructive" loading={form.formState.isSubmitting}>
                {t("shortfall.confirm")}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
