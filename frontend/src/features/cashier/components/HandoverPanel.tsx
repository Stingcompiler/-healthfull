import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { AlertCard } from "@/components/AlertCard";
import { DateText } from "@/components/DateText";
import { Form, SelectField, TextareaField, TextField } from "@/components/form";
import { MoneyText } from "@/components/MoneyText";
import { Button } from "@/components/ui/button";
import { useTranslateError } from "@/lib/api/translate-error";
import { usePermission } from "@/lib/auth/hooks";
import { vmsg } from "@/lib/validation";

import {
  useCancelHandover,
  useCreateHandover,
  useHandoverReceivers,
  useHandoverTargets,
  useReceiveHandover,
} from "../api";
import { isAmount, isPositiveAmount, negate, normalizeAmountInput } from "../lib/money";
import { useNames } from "../lib/use-names";
import type { Handover, HandoverIn, ShiftReport } from "../types";
import { NoteDialog } from "./NoteDialog";

const DESTINATIONS = ["next_shift", "safe", "bank_deposit", "supervisor"] as const;

const schema = z
  .object({
    destination: z.enum(DESTINATIONS),
    amount: z
      .string()
      .trim()
      .min(1, vmsg("validation.required"))
      .refine((v) => isAmount(v) && isPositiveAmount(v), vmsg("cashier:validation.positiveAmount")),
    toShift: z.string(),
    toUser: z.string(),
    bankReference: z.string().trim().max(100),
    note: z.string().trim().max(500),
  })
  .superRefine((v, ctx) => {
    if (v.destination === "next_shift" && !v.toShift) {
      ctx.addIssue({ code: "custom", path: ["toShift"], message: vmsg("validation.selectOption") });
    }
    if (v.destination === "supervisor" && !v.toUser) {
      ctx.addIssue({ code: "custom", path: ["toUser"], message: vmsg("validation.selectOption") });
    }
  });

type Values = z.infer<typeof schema>;

const EMPTY: Values = { destination: "safe", amount: "", toShift: "", toUser: "", bankReference: "", note: "" };

/** Where a handover went: the receiving shift, the named person, or the safe / the bank. */
function useRecipient() {
  const { t } = useTranslation("cashier");
  const names = useNames();
  return (h: Handover) =>
    [
      t(`handover.destination.${h.destination}`),
      h.to_shift_number ?? null,
      h.to_user && h.destination !== "next_shift" ? names.user(h.to_user) : null,
    ]
      .filter(Boolean)
      .join(" · ");
}

/** Cash leaving the drawer (FEATURES 7.6): to the next shift, the safe, the bank or a supervisor. */
export function HandoverPanel({ report }: { report: ShiftReport }) {
  const { t } = useTranslation(["cashier", "common", "errors"]);
  const translateError = useTranslateError();
  const names = useNames();
  const canHand = usePermission("payments.cash_handover");
  const create = useCreateHandover();
  const cancel = useCancelHandover();
  const targets = useHandoverTargets(canHand);
  const receivers = useHandoverReceivers(canHand);
  const recipient = useRecipient();
  const [error, setError] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState<Handover | null>(null);
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: EMPTY,
  });
  const destination = useWatch({ control: form.control, name: "destination" });
  if (!canHand) return null;

  // Every handover of this drawer that nobody confirmed yet is still in transit (any destination).
  const outgoing = report.handovers.filter((h) => h.shift_id === report.shift.id && !h.received_at && !h.cancelled_at);

  const submit = form.handleSubmit(async (v) => {
    setError(null);
    const body: HandoverIn = {
      amount: normalizeAmountInput(v.amount),
      destination: v.destination,
      to_shift_id: v.destination === "next_shift" ? Number(v.toShift) : null,
      to_user_id: v.destination === "supervisor" ? Number(v.toUser) : null,
      bank_reference: v.destination === "bank_deposit" ? v.bankReference : "",
      note: v.note,
    };
    try {
      await create.mutateAsync({ shiftId: report.shift.id, body });
      form.reset(EMPTY);
    } catch (e) {
      setError(translateError(e));
    }
  });

  return (
    <section className="card-surface flex min-w-0 flex-col gap-4 p-4 md:p-5" aria-labelledby="handover-title">
      <h2 id="handover-title" className="text-base font-semibold">
        {t("handover.title")}
      </h2>
      <Form {...form}>
        <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4" data-testid="handover-form">
          <div className="grid gap-4 sm:grid-cols-2">
            <SelectField
              control={form.control}
              name="destination"
              label={t("handover.to")}
              options={DESTINATIONS.map((d) => ({ value: d, label: t(`handover.destination.${d}`) }))}
              required
            />
            <TextField
              control={form.control}
              name="amount"
              label={t("handover.amount")}
              inputMode="decimal"
              dir="ltr"
              required
            />
            {destination === "next_shift" ? (
              <SelectField
                control={form.control}
                name="toShift"
                label={t("handover.toShift")}
                placeholder={t("handover.toShiftPlaceholder")}
                options={(targets.data ?? []).map((s) => ({
                  value: String(s.id),
                  label: `${s.number} · ${names.user(s.cashier)}`,
                }))}
                required
              />
            ) : null}
            {destination === "supervisor" ? (
              <SelectField
                control={form.control}
                name="toUser"
                label={t("handover.toUser")}
                placeholder={t("handover.toUserPlaceholder")}
                options={(receivers.data ?? []).map((u) => ({ value: String(u.id), label: names.user(u) }))}
                required
              />
            ) : null}
            {destination === "bank_deposit" ? (
              <TextField control={form.control} name="bankReference" label={t("handover.bankReference")} dir="ltr" />
            ) : null}
          </div>
          {destination === "safe" || destination === "bank_deposit" ? (
            <p className="text-sm text-muted">{t("handover.centerHint")}</p>
          ) : null}
          <TextareaField control={form.control} name="note" label={t("common:reason.note")} rows={2} />
          {error ? (
            <AlertCard variant="danger" title={t("errors:title")} live>
              {error}
            </AlertCard>
          ) : null}
          <div className="flex justify-end">
            <Button type="submit" variant="secondary" loading={form.formState.isSubmitting}>
              {t("handover.submit")}
            </Button>
          </div>
        </form>
      </Form>
      {outgoing.length > 0 ? (
        <div className="flex flex-col gap-2" data-testid="handovers-in-transit">
          <h3 className="text-sm font-medium">{t("handover.inTransit")}</h3>
          <ul className="flex flex-col divide-y divide-border text-sm">
            {outgoing.map((h) => (
              <li key={h.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <span className="flex min-w-0 flex-wrap items-center gap-2">
                  <bdi>{h.number}</bdi>
                  <span className="text-muted">{recipient(h)}</span>
                  {/* Cash leaving this drawer: a minus, as in the shift report. */}
                  <MoneyText value={negate(h.amount)} toneNegative />
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  aria-label={t("handover.cancelFor", { number: h.number })}
                  onClick={() => {
                    setCancelling(h);
                  }}
                >
                  {t("handover.cancel")}
                </Button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <NoteDialog
        open={cancelling !== null}
        onOpenChange={(o) => {
          if (!o) setCancelling(null);
        }}
        title={t("handover.cancelTitle")}
        description={t("handover.cancelDescription")}
        label={t("common:reason.note")}
        confirmLabel={t("handover.cancel")}
        destructive
        onSubmit={(note) => cancel.mutateAsync({ handoverId: cancelling?.id ?? 0, note })}
      />
    </section>
  );
}

/** Cash handed to this user that waits to be received (it blocks their shift's close). */
export function IncomingHandovers({ handovers }: { handovers: readonly Handover[] }) {
  const { t } = useTranslation(["cashier", "errors"]);
  const translateError = useTranslateError();
  const names = useNames();
  const recipient = useRecipient();
  const receive = useReceiveHandover();
  const [error, setError] = useState<string | null>(null);
  if (handovers.length === 0) return null;
  return (
    <section className="card-surface flex min-w-0 flex-col gap-3 p-4 md:p-5" data-testid="incoming-handovers">
      <h2 className="text-base font-semibold">{t("handover.incomingTitle", { count: handovers.length })}</h2>
      <ul className="flex flex-col divide-y divide-border text-sm">
        {handovers.map((h) => (
          <li key={h.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
            <span className="flex flex-wrap items-center gap-2">
              <bdi>{h.number}</bdi>
              <span className="text-muted">
                {names.user(h.handed_by)} · <bdi>{h.shift_number}</bdi>
              </span>
              <span className="text-muted">{recipient(h)}</span>
              <DateText value={h.handed_at} format="time" />
              <MoneyText value={h.amount} />
            </span>
            <Button
              size="sm"
              aria-label={t("handover.receiveFor", { number: h.number })}
              loading={receive.isPending && receive.variables === h.id}
              onClick={() => {
                setError(null);
                receive.mutateAsync(h.id).catch((e: unknown) => {
                  setError(translateError(e));
                });
              }}
            >
              {t("handover.receive")}
            </Button>
          </li>
        ))}
      </ul>
      {error ? (
        <AlertCard variant="danger" title={t("errors:title")} live>
          {error}
        </AlertCard>
      ) : null}
    </section>
  );
}
