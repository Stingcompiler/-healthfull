import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useState } from "react";
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
import { useTranslateError } from "@/lib/api/translate-error";
import { vmsg } from "@/lib/validation";

import { useDiscountLine, useReasons } from "../api";
import { isAmount, normalizeAmountInput } from "../lib/money";
import { useNames } from "../lib/use-names";
import type { InvoiceLine } from "../types";
import { ApproverFields } from "./ApproverFields";

const schema = z
  .object({
    reason: z.string().min(1, vmsg("validation.selectOption")),
    mode: z.enum(["amount", "percent"]),
    value: z.string().trim().min(1, vmsg("validation.required")).refine(isAmount, vmsg("cashier:validation.amount")),
    note: z.string().trim().max(500),
    withApprover: z.boolean(),
    username: z.string().trim(),
    password: z.string(),
  })
  .superRefine((v, ctx) => {
    if (!v.withApprover) return;
    if (!v.username) ctx.addIssue({ code: "custom", path: ["username"], message: vmsg("validation.required") });
    if (!v.password) ctx.addIssue({ code: "custom", path: ["password"], message: vmsg("validation.required") });
  });

type Values = z.infer<typeof schema>;

const EMPTY: Values = {
  reason: "",
  mode: "amount",
  value: "",
  note: "",
  withApprover: false,
  username: "",
  password: "",
};

/** Discount one draft line's patient share (FEATURES 5.9): reason, limit, desk approval. */
export function DiscountDialog({
  invoiceId,
  line,
  open,
  onOpenChange,
}: {
  invoiceId: number;
  line: InvoiceLine | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation(["cashier", "common", "errors"]);
  const translateError = useTranslateError();
  const names = useNames();
  const reasons = useReasons("discount", open);
  const discount = useDiscountLine();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: EMPTY });
  const { reset, control } = form;
  const withApprover = useWatch({ control, name: "withApprover" });
  const mode = useWatch({ control, name: "mode" });

  useEffect(() => {
    if (open) {
      reset(EMPTY);
      setError(null);
    }
  }, [open, reset]);

  const submit = form.handleSubmit(async (v) => {
    if (!line) return;
    setError(null);
    const value = normalizeAmountInput(v.value);
    try {
      await discount.mutateAsync({
        invoiceId,
        lineId: line.id,
        body: {
          reason: v.reason,
          note: v.note,
          amount: v.mode === "amount" ? value : null,
          percent: v.mode === "percent" ? value : null,
          approver: v.withApprover ? { username: v.username, password: v.password } : null,
        },
      });
      onOpenChange(false);
    } catch (e) {
      form.setValue("password", "");
      setError(translateError(e));
    }
  });

  return (
    <Dialog open={open} onOpenChange={(next) => !form.formState.isSubmitting && onOpenChange(next)}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("discount.title")}</DialogTitle>
          <DialogDescription>{t("discount.description")}</DialogDescription>
        </DialogHeader>
        {line ? (
          <p className="flex flex-wrap items-center justify-between gap-2 rounded-control bg-subtle px-3 py-2 text-sm">
            <span className="min-w-0 font-medium">{names.name(line.service)}</span>
            <span className="text-muted">
              {t("discount.patientShare")} <MoneyText value={line.patient_share} />
            </span>
          </p>
        ) : null}
        <Form {...form}>
          <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4" data-testid="discount-form">
            <SelectField
              control={control}
              name="reason"
              label={t("common:reason.code")}
              placeholder={t("common:reason.codePlaceholder")}
              options={(reasons.data ?? []).map((r) => ({ value: r.code, label: names.label(r) }))}
              required
            />
            <RadioGroupField
              control={control}
              name="mode"
              label={t("discount.mode")}
              options={[
                { value: "amount", label: t("discount.byAmount") },
                { value: "percent", label: t("discount.byPercent") },
              ]}
            />
            <TextField
              control={control}
              name="value"
              label={mode === "percent" ? t("discount.percent") : t("discount.amount")}
              inputMode="decimal"
              dir="ltr"
              required
            />
            <TextareaField control={control} name="note" label={t("common:reason.note")} rows={2} maxLength={500} />
            <ApproverFields
              control={control}
              enabledName="withApprover"
              usernameName="username"
              passwordName="password"
              enabled={withApprover}
            />
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
                {t("discount.submit")}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
