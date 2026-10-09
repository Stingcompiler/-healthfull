import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { AlertCard } from "@/components/AlertCard";
import { Form, RadioGroupField, TextField } from "@/components/form";
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

import { useRecordResponses } from "../api";
import { useClaimNames } from "../lib/names";
import type { ClaimLine } from "../types";

function schemaFor(claimed: string) {
  return z
    .object({
      outcome: z.enum(["accepted", "partial", "rejected"]),
      accepted: z.string().trim(),
      reason: z.string().trim().max(300),
      reference: z.string().trim().max(100),
    })
    .superRefine((v, ctx) => {
      if (v.outcome === "partial") {
        if (!isAmount(v.accepted)) {
          ctx.addIssue({ code: "custom", path: ["accepted"], message: vmsg("claims:validation.amount") });
        } else if (!isPositiveAmount(v.accepted) || compareAmounts(v.accepted, claimed) !== -1) {
          ctx.addIssue({ code: "custom", path: ["accepted"], message: vmsg("claims:validation.partialRange") });
        }
      }
      if (v.outcome !== "accepted" && v.reason === "") {
        ctx.addIssue({ code: "custom", path: ["reason"], message: vmsg("claims:validation.payerReason") });
      }
    });
}

type Values = z.infer<ReturnType<typeof schemaFor>>;

interface ResponseDialogProps {
  claimId: number;
  line: ClaimLine | null;
  onOpenChange: (open: boolean) => void;
}

/** Mounted only while open, so every answer starts from a fresh form. */
export function ResponseDialog(props: ResponseDialogProps) {
  return props.line ? <ResponseDialogOpen {...props} line={props.line} /> : null;
}

/**
 * The payer's answer for one claim line (FEATURES 11.4): accepted in full, partly (the
 * accepted amount; the rest is rejected) or rejected, with the payer's reason for any
 * rejected part and the remittance reference.
 */
function ResponseDialogOpen({ claimId, line, onOpenChange }: ResponseDialogProps & { line: ClaimLine }) {
  const { t } = useTranslation(["claims", "common", "errors"]);
  const translateError = useTranslateError();
  const names = useClaimNames();
  const record = useRecordResponses();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<Values>({
    resolver: zodResolver(schemaFor(line.amount_claimed)),
    defaultValues: { outcome: "accepted", accepted: "", reason: "", reference: "" },
  });
  const outcome = useWatch({ control: form.control, name: "outcome" });

  const submit = form.handleSubmit(async (v) => {
    setError(null);
    try {
      await record.mutateAsync({
        claimId,
        responses: [
          {
            claim_line_id: line.id,
            outcome: v.outcome,
            accepted: v.outcome === "partial" ? normalizeAmountInput(v.accepted) : null,
            reason: v.outcome === "accepted" ? "" : v.reason,
            reference: v.reference,
          },
        ],
      });
      onOpenChange(false);
    } catch (e) {
      setError(translateError(e));
    }
  });

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent data-testid="response-dialog">
        <DialogHeader>
          <DialogTitle>{t("response.title")}</DialogTitle>
          <DialogDescription>{t("response.description")}</DialogDescription>
        </DialogHeader>
        <p className="flex flex-wrap items-center justify-between gap-2 rounded-control bg-subtle px-3 py-2 text-sm">
          <span className="min-w-0">
            {names.text(line.description_ar, line.description_en)} · {names.person(line.patient)}
          </span>
          <MoneyText value={line.amount_claimed} />
        </p>
        <Form {...form}>
          <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4">
            <RadioGroupField
              control={form.control}
              name="outcome"
              label={t("response.outcome")}
              options={[
                { value: "accepted", label: t("response.accepted") },
                { value: "partial", label: t("response.partial") },
                { value: "rejected", label: t("response.rejected") },
              ]}
            />
            {outcome === "partial" ? (
              <TextField
                control={form.control}
                name="accepted"
                label={t("response.acceptedAmount")}
                inputMode="decimal"
                dir="ltr"
                required
              />
            ) : null}
            {outcome !== "accepted" ? (
              <TextField control={form.control} name="reason" label={t("response.reason")} required />
            ) : null}
            <TextField control={form.control} name="reference" label={t("response.reference")} dir="auto" />
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
              <Button type="submit" loading={form.formState.isSubmitting} data-testid="response-submit">
                {t("response.save")}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
