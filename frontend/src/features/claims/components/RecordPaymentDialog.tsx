import { zodResolver } from "@hookform/resolvers/zod";
import { useId, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { AlertCard } from "@/components/AlertCard";
import { Form, RadioGroupField, SelectField, TextareaField, TextField } from "@/components/form";
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
import { Input } from "@/components/ui/input";
import { DateField } from "@/features/admin/components/DateField";
import {
  compareAmounts,
  isAmount,
  isPositiveAmount,
  normalizeAmountInput,
  sumAmounts,
} from "@/features/cashier/lib/money";
import { centerToday } from "@/features/patients/lib";
import { useTranslateError } from "@/lib/api/translate-error";
import { vmsg } from "@/lib/validation";

import { useClaimOptions, usePayable, useRecordPayerPayment } from "../api";
import { useClaimNames } from "../lib/names";
import type { ClaimPayerPayment } from "../types";
import { Period } from "./Period";

const schema = z
  .object({
    payer: z.string().min(1, vmsg("validation.selectOption")),
    method: z.enum(["bank_transfer", "cheque", "cash"]),
    bank: z.string(),
    reference: z.string().trim().max(100),
    receivedOn: z.string().min(1, vmsg("validation.required")),
    amount: z
      .string()
      .trim()
      .min(1, vmsg("validation.required"))
      .refine(isAmount, vmsg("claims:validation.amount"))
      .refine(isPositiveAmount, vmsg("claims:validation.positive")),
    allocation: z.enum(["oldest", "claims"]),
    note: z.string().trim().max(500),
  })
  .superRefine((v, ctx) => {
    if (v.method === "bank_transfer") {
      if (!v.bank) ctx.addIssue({ code: "custom", path: ["bank"], message: vmsg("validation.selectOption") });
      if (!v.reference) ctx.addIssue({ code: "custom", path: ["reference"], message: vmsg("validation.required") });
    }
  });

type Values = z.infer<typeof schema>;

interface RecordPaymentDialogProps {
  open: boolean;
  payerId?: number;
  onOpenChange: (open: boolean) => void;
  onRecorded: (payment: ClaimPayerPayment) => void;
}

/** Mounted only while open, so every payment starts from a fresh form. */
export function RecordPaymentDialog(props: RecordPaymentDialogProps) {
  return props.open ? <RecordPaymentDialogOpen {...props} /> : null;
}

/**
 * Money received from a payer (FEATURES 11.6), allocated in full to its claims: oldest
 * accepted amounts first, or the amounts the payer's remittance advice names per claim. A
 * transfer goes to the bank, a cheque waits until it clears, and cash goes into the
 * recorder's own open shift (invariant 7: payer share becomes money only here).
 */
function RecordPaymentDialogOpen({ payerId, onOpenChange, onRecorded }: RecordPaymentDialogProps) {
  const { t } = useTranslation(["claims", "common", "errors"]);
  const translateError = useTranslateError();
  const names = useClaimNames();
  const ids = useId();
  const options = useClaimOptions();
  const record = useRecordPayerPayment();
  const [error, setError] = useState<string | null>(null);
  const [perClaim, setPerClaim] = useState<Record<number, string>>({});
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      payer: payerId ? String(payerId) : "",
      method: "bank_transfer",
      bank: "",
      reference: "",
      receivedOn: centerToday(),
      amount: "",
      allocation: "oldest",
      note: "",
    },
  });
  const [payer, method, allocation, amount] = useWatch({
    control: form.control,
    name: ["payer", "method", "allocation", "amount"],
  });
  const payable = usePayable(payer ? Number(payer) : undefined);
  const openShift = options.data?.open_shift ?? null;
  // Only the claims of the payer now chosen count (amounts typed for another payer are dropped).
  const entered = (payable.data ?? [])
    .map((c) => [c.id, (perClaim[c.id] ?? "").trim()] as const)
    .filter(([, v]) => v !== "");
  const allocated = sumAmounts(entered.map(([, v]) => v)) ?? null;
  const balanced =
    allocation === "oldest" || (allocated !== null && isAmount(amount) && compareAmounts(allocated, amount) === 0);

  const submit = form.handleSubmit(async (v) => {
    setError(null);
    if (v.allocation === "claims" && !balanced) {
      setError(t("payments.unbalanced"));
      return;
    }
    try {
      const payment = await record.mutateAsync({
        payer_id: Number(v.payer),
        amount: normalizeAmountInput(v.amount),
        method: v.method,
        bank_id: v.bank && v.method !== "cash" ? Number(v.bank) : null,
        reference: v.method === "cash" ? "" : v.reference,
        received_on: v.receivedOn,
        claims:
          v.allocation === "claims"
            ? entered.map(([claimId, value]) => ({ claim_id: claimId, amount: normalizeAmountInput(value) }))
            : null,
        lines: null,
        note: v.note,
      });
      onRecorded(payment);
      onOpenChange(false);
    } catch (e) {
      setError(translateError(e));
    }
  });

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto" data-testid="payer-payment-dialog">
        <DialogHeader>
          <DialogTitle>{t("payments.recordTitle")}</DialogTitle>
          <DialogDescription>{t("payments.recordDescription")}</DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4">
            <SelectField
              control={form.control}
              name="payer"
              label={t("payments.payer")}
              required
              options={(options.data?.payers ?? [])
                .filter((p) => p.active || String(p.id) === payer)
                .map((p) => ({ value: String(p.id), label: names.name(p) }))}
            />
            <RadioGroupField
              control={form.control}
              name="method"
              label={t("payments.method")}
              options={[
                { value: "bank_transfer", label: t("method.bank_transfer") },
                { value: "cheque", label: t("method.cheque") },
                { value: "cash", label: t("method.cash"), disabled: openShift === null },
              ]}
              description={
                method === "cash" && openShift
                  ? t("payments.cashIntoShift", { shift: openShift.number })
                  : openShift === null
                    ? t("payments.cashNeedsShift")
                    : undefined
              }
            />
            {method !== "cash" ? (
              <div className="grid gap-4 sm:grid-cols-2">
                <SelectField
                  control={form.control}
                  name="bank"
                  label={t("payments.bank")}
                  required={method === "bank_transfer"}
                  options={(options.data?.banks ?? []).map((b) => ({ value: String(b.id), label: names.name(b) }))}
                />
                <TextField
                  control={form.control}
                  name="reference"
                  label={method === "cheque" ? t("payments.chequeNo") : t("payments.reference")}
                  required={method === "bank_transfer"}
                  dir="ltr"
                />
              </div>
            ) : null}
            <div className="grid gap-4 sm:grid-cols-2">
              <TextField
                control={form.control}
                name="amount"
                label={t("payments.amount")}
                inputMode="decimal"
                dir="ltr"
                required
              />
              <DateField control={form.control} name="receivedOn" label={t("payments.receivedOn")} required />
            </div>
            <RadioGroupField
              control={form.control}
              name="allocation"
              label={t("payments.allocation")}
              options={[
                { value: "oldest", label: t("payments.oldestFirst") },
                { value: "claims", label: t("payments.perClaim") },
              ]}
            />
            {allocation === "claims" ? (
              <fieldset className="grid gap-2" data-testid="allocation-claims">
                <legend className="sr-only">{t("payments.perClaim")}</legend>
                {!payer ? (
                  <p className="text-sm text-muted">{t("payments.choosePayerFirst")}</p>
                ) : (payable.data ?? []).length === 0 ? (
                  <p className="text-sm text-muted">{t("payments.nothingPayable")}</p>
                ) : (
                  (payable.data ?? []).map((c) => {
                    const id = `${ids}-claim-${String(c.id)}`;
                    return (
                      <div
                        key={c.id}
                        className="flex flex-col gap-2 rounded-control border border-border p-3 sm:flex-row sm:items-center sm:justify-between"
                      >
                        <label htmlFor={id} className="flex min-w-0 flex-col text-sm">
                          <bdi className="font-medium">{c.number}</bdi>
                          <span className="text-xs text-muted">
                            <Period start={c.period_start} end={c.period_end} />
                          </span>
                          <span className="flex flex-wrap items-center gap-x-1 text-xs">
                            {t("payments.unpaid")}: <MoneyText value={c.unpaid_total} currency={false} />
                          </span>
                        </label>
                        <Input
                          id={id}
                          inputMode="decimal"
                          dir="ltr"
                          className="sm:w-40"
                          value={perClaim[c.id] ?? ""}
                          onChange={(e) => {
                            setPerClaim((prev) => ({ ...prev, [c.id]: e.target.value }));
                          }}
                          data-testid="allocation-amount"
                        />
                      </div>
                    );
                  })
                )}
                <p className="flex flex-wrap items-center gap-x-2 text-sm" data-testid="allocation-total">
                  <span className="text-muted">{t("payments.allocated")}</span>
                  <MoneyText value={allocated ?? "0.00"} />
                  {!balanced ? <span className="text-warning-fg">{t("payments.mustEqual")}</span> : null}
                </p>
              </fieldset>
            ) : null}
            <TextareaField control={form.control} name="note" label={t("payments.note")} />
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
              <Button type="submit" loading={form.formState.isSubmitting} data-testid="payer-payment-submit">
                {t("payments.record")}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
