import { zodResolver } from "@hookform/resolvers/zod";
import { Link } from "@tanstack/react-router";
import { Banknote, CreditCard, Landmark, PiggyBank, Printer, QrCode } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { AlertCard } from "@/components/AlertCard";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
  SelectField,
  TextareaField,
  TextField,
} from "@/components/form";
import { KbdCombo } from "@/components/Kbd";
import { MoneyText } from "@/components/MoneyText";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupSegment } from "@/components/ui/radio-group";
import { isApiError } from "@/lib/api/errors";
import { useTranslateError } from "@/lib/api/translate-error";
import { usePermission } from "@/lib/auth/hooks";
import { useShortcut } from "@/lib/hooks/use-shortcut";
import { vmsg } from "@/lib/validation";

import { useAllocatePayment, useBanks, useReasons, useRecordPayment } from "../api";
import {
  compareAmounts,
  isAmount,
  isPositiveAmount,
  normalizeAmountInput,
  subtractAmounts,
  sumAmounts,
} from "../lib/money";
import { useNames } from "../lib/use-names";
import { PAYMENT_METHODS, REFERENCE_METHODS, type Payment, type PaymentMethod, type VisitBilling } from "../types";
import { ApproverFields } from "./ApproverFields";

export const PAY_SHORTCUT = "mod+enter";
export const AMOUNT_SHORTCUT = "f9";

const METHOD_ICONS = {
  cash: Banknote,
  bank_transfer: Landmark,
  qr: QrCode,
  card: CreditCard,
  patient_credit: PiggyBank,
} as const;

const schema = z
  .object({
    method: z.enum(["cash", "bank_transfer", "qr", "card", "patient_credit"]),
    amount: z
      .string()
      .trim()
      .min(1, vmsg("validation.required"))
      .refine((v) => isAmount(v) && isPositiveAmount(v), vmsg("cashier:validation.positiveAmount")),
    tendered: z.string().trim(),
    bank: z.string(),
    reference: z.string().trim().max(100),
    transferDate: z.string(),
    senderName: z.string().trim().max(200),
    override: z.boolean(),
    overrideReason: z.string(),
    overrideNote: z.string().trim().max(1000),
    withApprover: z.boolean(),
    username: z.string().trim(),
    password: z.string(),
  })
  .superRefine((v, ctx) => {
    const required = (path: string) => {
      ctx.addIssue({ code: "custom", path: [path], message: vmsg("validation.required") });
    };
    if (v.tendered && !isAmount(v.tendered)) {
      ctx.addIssue({ code: "custom", path: ["tendered"], message: vmsg("cashier:validation.amount") });
    }
    if ((REFERENCE_METHODS as readonly string[]).includes(v.method)) {
      if (!v.bank) required("bank");
      if (!v.reference) required("reference");
    }
    if (v.override) {
      if (!v.overrideReason) required("overrideReason");
      if (v.withApprover && !v.username) required("username");
      if (v.withApprover && !v.password) required("password");
    }
  });

type Values = z.infer<typeof schema>;

function defaults(amount: string): Values {
  return {
    method: "cash",
    amount,
    tendered: "",
    bank: "",
    reference: "",
    transferDate: "",
    senderName: "",
    override: false,
    overrideReason: "",
    overrideNote: "",
    withApprover: false,
    username: "",
    password: "",
  };
}

/**
 * Take the patient's money into the cashier's own open shift (FEATURES 6.1-6.5). The amount
 * goes to this visit's open invoices (the server allocates oldest first within the visit);
 * the cashier may also include the patient's other visits. Anything above them stays as
 * patient credit, which can be spent on open invoices afterwards. Transfers, QR and card start
 * pending until a supervisor confirms them.
 */
export function PaymentPanel({ billing, shiftOpen }: { billing: VisitBilling; shiftOpen: boolean }) {
  const { t } = useTranslation(["cashier", "common", "errors"]);
  const translateError = useTranslateError();
  const names = useNames();
  const canPay = usePermission("payments.take_payment");
  const record = useRecordPayment();
  const allocate = useAllocatePayment();
  const banks = useBanks(canPay);
  const overrideReasons = useReasons("override", canPay);
  const [error, setError] = useState<string | null>(null);
  const [paid, setPaid] = useState<{ payment: Payment; change: string | null } | null>(null);
  const [allocateError, setAllocateError] = useState<string | null>(null);
  const [includeOthers, setIncludeOthers] = useState(false);
  const visitId = billing.visit.id;
  const visitDue =
    sumAmounts(billing.open_invoices.filter((i) => i.visit_id === visitId).map((i) => i.outstanding)) ?? "0.00";
  const otherDue = subtractAmounts(billing.balance.outstanding, visitDue) ?? "0.00";
  const hasOthers = isPositiveAmount(otherDue);
  const due = includeOthers && hasOthers ? billing.balance.outstanding : visitDue;
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: defaults(due) });
  const { control, setValue } = form;
  const method = useWatch({ control, name: "method" });
  const amount = useWatch({ control, name: "amount" });
  const tendered = useWatch({ control, name: "tendered" });
  const override = useWatch({ control, name: "override" });
  const withApprover = useWatch({ control, name: "withApprover" });
  useEffect(() => {
    setValue("amount", due);
  }, [due, setValue]);
  const isReference = (REFERENCE_METHODS as readonly string[]).includes(method);
  const spendable = billing.balance.spendable;
  const methods = PAYMENT_METHODS.filter((m) => m !== "patient_credit" || isPositiveAmount(spendable));
  const change = method === "cash" && tendered && amount ? subtractAmounts(tendered, amount) : null;
  const changeValid = change !== null && compareAmounts(change, "0") !== -1;

  const submit = form.handleSubmit(async (v) => {
    setError(null);
    const isRef = (REFERENCE_METHODS as readonly string[]).includes(v.method);
    try {
      const payment = await record.mutateAsync({
        patient_id: billing.patient.id,
        method: v.method,
        amount: normalizeAmountInput(v.amount),
        bank: isRef ? v.bank : null,
        reference: isRef ? v.reference : "",
        transfer_date: isRef && v.transferDate ? v.transferDate : null,
        sender_name: isRef ? v.senderName : "",
        auto: true,
        visit_id: includeOthers ? null : visitId,
        note: "",
        override:
          isRef && v.override
            ? {
                reason: v.overrideReason,
                note: v.overrideNote,
                approver: v.withApprover ? { username: v.username, password: v.password } : null,
              }
            : null,
      });
      setPaid({ payment, change: v.method === "cash" && v.tendered ? subtractAmounts(v.tendered, v.amount) : null });
      setAllocateError(null);
      form.reset(defaults(due));
    } catch (e) {
      setValue("password", "");
      if (isApiError(e) && e.code === "DUPLICATE_REFERENCE") setValue("override", true);
      setError(translateError(e));
    }
  });

  useShortcut(PAY_SHORTCUT, () => void submit(), { enabled: canPay && shiftOpen, allowInInputs: true });
  useShortcut(
    AMOUNT_SHORTCUT,
    () => {
      form.setFocus("amount", { shouldSelect: true });
    },
    { enabled: canPay && shiftOpen, allowInInputs: true },
  );

  const spendRemainder = async () => {
    if (!paid) return;
    setAllocateError(null);
    try {
      const payment = await allocate.mutateAsync({ paymentId: paid.payment.id, visitId: null });
      setPaid({ ...paid, payment });
    } catch (e) {
      setAllocateError(translateError(e));
    }
  };
  useShortcut(
    ["alt+1", "alt+2", "alt+3", "alt+4", "alt+5"],
    (event) => {
      const index = Number(event.code.replace("Digit", "")) - 1;
      const next = methods[index];
      if (next) setValue("method", next);
    },
    { enabled: canPay && shiftOpen, allowInInputs: true },
  );

  if (!canPay) return null;

  return (
    <section
      aria-labelledby="payment-title"
      className="card-surface flex min-w-0 flex-col gap-4 p-4 md:p-5"
      data-testid="payment-panel"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="payment-title" className="text-base font-semibold">
          {t("payment.title")}
        </h2>
        <span className="text-sm text-muted" data-testid="payment-due">
          {t("payment.due")} <MoneyText value={due} className="text-fg" />
        </span>
      </div>
      {hasOthers ? (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-control border border-border px-3 py-2 text-sm">
          <span className="text-muted">
            {t("payment.otherVisitsDue")} <MoneyText value={otherDue} className="text-fg" />
          </span>
          <div className="flex items-center gap-2">
            <Checkbox
              id="payment-include-others"
              checked={includeOthers}
              onCheckedChange={(value) => {
                setIncludeOthers(value === true);
              }}
              data-testid="include-other-visits"
            />
            <Label htmlFor="payment-include-others">{t("payment.includeOthers")}</Label>
          </div>
        </div>
      ) : null}

      {paid ? (
        <AlertCard
          variant="success"
          title={t("payment.doneTitle", { number: paid.payment.number })}
          live
          onDismiss={() => {
            setPaid(null);
          }}
          action={
            <Button asChild variant="outline" size="sm">
              <Link
                to="/cashier/receipts/$paymentId"
                params={{ paymentId: String(paid.payment.id) }}
                search={{ visit: visitId }}
                data-testid="print-receipt"
              >
                <Printer aria-hidden="true" />
                {t("payment.printReceipt")}
              </Link>
            </Button>
          }
        >
          <span className="flex flex-wrap items-center gap-2" data-testid="payment-done">
            <MoneyText value={paid.payment.amount} />
            <StatusBadge
              size="sm"
              status={paid.payment.verification === "pending" ? "pending_verification" : "confirmed"}
            />
            {paid.change && compareAmounts(paid.change, "0") === 1 ? (
              <span>
                {t("payment.changeDue")} <MoneyText value={paid.change} />
              </span>
            ) : null}
            {paid.payment.unallocated !== "0.00" ? (
              <span data-testid="payment-unallocated">
                {t("payment.toCredit")} <MoneyText value={paid.payment.unallocated} />
              </span>
            ) : null}
          </span>
          {paid.payment.unallocated !== "0.00" &&
          paid.payment.verification !== "rejected" &&
          isPositiveAmount(billing.balance.outstanding) ? (
            <span className="mt-2 flex flex-wrap items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                loading={allocate.isPending}
                onClick={() => void spendRemainder()}
                data-testid="spend-remainder"
              >
                {t("payment.spendRemainder")}
              </Button>
              <span className="text-xs text-muted">{t("payment.spendRemainderHint")}</span>
            </span>
          ) : null}
          {allocateError ? <span className="mt-2 block text-sm text-danger-fg">{allocateError}</span> : null}
        </AlertCard>
      ) : null}

      {!shiftOpen ? (
        <AlertCard variant="warning" title={t("payment.noShiftTitle")}>
          {t("payment.noShiftBody")}
        </AlertCard>
      ) : (
        <Form {...form}>
          <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4" data-testid="payment-form">
            {/* A radio group, not tabs: the methods show no panel of their own (one form). */}
            <RadioGroup
              value={method}
              onValueChange={(value) => {
                setValue("method", value as PaymentMethod);
                setError(null);
              }}
              aria-label={t("payment.method.label")}
              className="flex w-full flex-wrap justify-start gap-1 rounded-control bg-subtle p-1"
              data-testid="payment-methods"
            >
              {methods.map((m, i) => {
                const Icon = METHOD_ICONS[m];
                return (
                  <RadioGroupSegment
                    key={m}
                    value={m}
                    className="h-11 flex-none md:h-9"
                    data-testid={`method-${m}`}
                    aria-keyshortcuts={`Alt+${String(i + 1)}`}
                  >
                    <Icon aria-hidden="true" />
                    {t(`payment.method.${m}`)}
                    <span aria-hidden="true" className="ms-1 hidden lg:inline-flex">
                      <KbdCombo combo={`alt+${String(i + 1)}`} />
                    </span>
                  </RadioGroupSegment>
                );
              })}
            </RadioGroup>

            <div className="grid gap-4 sm:grid-cols-2">
              <TextField
                control={control}
                name="amount"
                label={t("payment.amount")}
                inputMode="decimal"
                dir="ltr"
                required
              />
              {method === "cash" ? (
                <TextField
                  control={control}
                  name="tendered"
                  label={t("payment.tendered")}
                  inputMode="decimal"
                  dir="ltr"
                />
              ) : null}
              {method === "patient_credit" ? (
                <p className="self-end text-sm text-muted">
                  {t("payment.spendable")} <MoneyText value={spendable} className="text-fg" />
                </p>
              ) : null}
            </div>

            {method === "cash" && change !== null ? (
              <p
                className={changeValid ? "text-base font-semibold" : "text-sm text-danger-fg"}
                data-testid="change-due"
                aria-live="polite"
              >
                {changeValid ? (
                  <>
                    {t("payment.changeDue")} <MoneyText value={change} />
                  </>
                ) : (
                  t("payment.tenderedShort")
                )}
              </p>
            ) : null}

            {isReference ? (
              <div className="grid gap-4 sm:grid-cols-2">
                <SelectField
                  control={control}
                  name="bank"
                  label={t("payment.bank")}
                  placeholder={t("payment.bankPlaceholder")}
                  options={(banks.data ?? []).map((b) => ({ value: b.code, label: names.name(b) }))}
                  required
                />
                <TextField control={control} name="reference" label={t("payment.reference")} dir="ltr" required />
                <TextField control={control} name="senderName" label={t("payment.senderName")} />
                <FormField
                  control={control}
                  name="transferDate"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>{t("payment.transferDate")}</FormLabel>
                      <FormControl>
                        <Input type="date" dir="ltr" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>
            ) : null}

            {isReference && override ? (
              <fieldset
                className="grid gap-3 rounded-control border border-warning-border bg-warning-bg/40 p-3"
                data-testid="override"
              >
                <legend className="px-1 text-sm font-semibold">{t("payment.override.title")}</legend>
                <p className="text-sm text-muted">{t("payment.override.description")}</p>
                <SelectField
                  control={control}
                  name="overrideReason"
                  label={t("common:reason.code")}
                  placeholder={t("common:reason.codePlaceholder")}
                  options={(overrideReasons.data ?? []).map((r) => ({ value: r.code, label: names.label(r) }))}
                  required
                />
                <TextareaField control={control} name="overrideNote" label={t("common:reason.note")} rows={2} />
                <ApproverFields
                  control={control}
                  enabledName="withApprover"
                  usernameName="username"
                  passwordName="password"
                  enabled={withApprover}
                  description={t("payment.override.approver")}
                />
              </fieldset>
            ) : null}

            {error ? (
              <AlertCard variant="danger" title={t("errors:title")} live>
                {error}
              </AlertCard>
            ) : null}

            <div className="flex flex-wrap items-center justify-end gap-2">
              <Button type="submit" size="lg" loading={form.formState.isSubmitting} data-testid="take-payment">
                {t("payment.submit")}
                <KbdCombo combo={PAY_SHORTCUT} className="ms-1 hidden md:inline-flex" />
              </Button>
            </div>
          </form>
        </Form>
      )}
    </section>
  );
}
