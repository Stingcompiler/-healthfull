import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { AlertCard } from "@/components/AlertCard";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Form, SelectField, TextareaField, TextField } from "@/components/form";
import { MoneyText } from "@/components/MoneyText";
import { Button } from "@/components/ui/button";
import { vmsg } from "@/lib/validation";

import { useCloseShift, useReasons } from "../api";
import { compareAmounts, isAmount, normalizeAmountInput, subtractAmounts } from "../lib/money";
import { useNames } from "../lib/use-names";
import type { ShiftReport } from "../types";

const schema = z.object({
  counted: z
    .string()
    .trim()
    .min(1, vmsg("validation.required"))
    .refine(isAmount, vmsg("cashier:validation.amount")),
  reason: z.string(),
  note: z.string().trim().max(1000),
});

type Values = z.infer<typeof schema>;

/**
 * Close the shift with the counted cash (FEATURES 7.2). The server computes the variance and
 * refuses a non-zero one without an explanation; the hint here only helps the cashier.
 */
export function CloseShiftForm({ report, onClosed }: { report: ShiftReport; onClosed: (r: ShiftReport) => void }) {
  const { t } = useTranslation(["cashier", "common"]);
  const names = useNames();
  const reasons = useReasons("variance");
  const close = useCloseShift();
  const [confirming, setConfirming] = useState<Values | null>(null);
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { counted: "", reason: "", note: "" } });
  const counted = useWatch({ control: form.control, name: "counted" });
  const variance = counted && isAmount(counted) ? subtractAmounts(counted, report.expected_cash) : null;
  const hasVariance = variance !== null && compareAmounts(variance, "0") !== 0;

  const submit = form.handleSubmit((v) => {
    setConfirming(v);
  });

  return (
    <section className="card-surface flex min-w-0 flex-col gap-4 p-4 md:p-5" aria-labelledby="close-title">
      <h2 id="close-title" className="text-base font-semibold">
        {t("close.title")}
      </h2>
      <p className="text-sm text-muted">{t("close.description")}</p>
      <Form {...form}>
        <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4" data-testid="close-shift-form">
          <div className="grid gap-4 sm:grid-cols-2">
            <TextField
              control={form.control}
              name="counted"
              label={t("close.counted")}
              inputMode="decimal"
              dir="ltr"
              required
            />
            <div className="flex flex-col justify-end gap-1 text-sm">
              <span className="text-muted">
                {t("report.expectedCash")} <MoneyText value={report.expected_cash} className="text-fg" />
              </span>
              {variance !== null ? (
                <span className={hasVariance ? "font-semibold text-warning-fg" : "text-success-fg"} aria-live="polite">
                  {t("report.variance")} <MoneyText value={variance} signed />
                </span>
              ) : null}
            </div>
          </div>
          {hasVariance ? (
            <AlertCard variant="warning" title={t("close.varianceTitle")}>
              {t("close.varianceBody")}
            </AlertCard>
          ) : null}
          <SelectField
            control={form.control}
            name="reason"
            label={t("close.reason")}
            placeholder={t("common:reason.codePlaceholder")}
            options={(reasons.data ?? []).map((r) => ({ value: r.code, label: names.label(r) }))}
            required={hasVariance}
          />
          <TextareaField control={form.control} name="note" label={t("common:reason.note")} rows={2} />
          <div className="flex justify-end">
            <Button type="submit" data-testid="close-shift">
              {t("close.submit")}
            </Button>
          </div>
        </form>
      </Form>
      <ConfirmDialog
        open={confirming !== null}
        onOpenChange={(o) => {
          if (!o) setConfirming(null);
        }}
        title={t("close.confirmTitle")}
        description={t("close.confirmDescription")}
        confirmLabel={t("close.submit")}
        onConfirm={async () => {
          if (!confirming) return;
          const closed = await close.mutateAsync({
            shiftId: report.shift.id,
            body: {
              counted: normalizeAmountInput(confirming.counted),
              reason: confirming.reason || null,
              note: confirming.note,
            },
          });
          onClosed(closed);
        }}
      />
    </section>
  );
}
