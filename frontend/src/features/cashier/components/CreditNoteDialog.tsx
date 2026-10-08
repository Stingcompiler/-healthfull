import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
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
} from "@/components/form";
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
import { useTranslateError } from "@/lib/api/translate-error";
import { translateMessage, vmsg } from "@/lib/validation";

import { useCreateCreditNote, useReasons } from "../api";
import { normalizeAmountInput } from "../lib/money";
import { useNames } from "../lib/use-names";
import type { Invoice } from "../types";

const WHOLE = /^\d+$/;

/**
 * Units per line are whole numbers from 0 to what is left of the line (Arabic-Indic digits
 * accepted, as everywhere at the desk); at least one unit overall. Text inputs, not
 * type=number: Chrome empties a number input typed in Arabic-Indic digits.
 */
function makeSchema(maxById: Record<string, number>) {
  return z
    .object({
      reason: z.string().min(1, vmsg("validation.selectOption")),
      note: z.string().trim().max(1000),
      qty: z.record(z.string(), z.string()),
    })
    .superRefine((v, ctx) => {
      let total = 0;
      let invalid = false;
      for (const [id, max] of Object.entries(maxById)) {
        const raw = normalizeAmountInput(v.qty[id] ?? "");
        if (raw === "") continue;
        if (!WHOLE.test(raw) || Number(raw) > max) {
          invalid = true;
          ctx.addIssue({ code: "custom", path: ["qty", id], message: vmsg("cashier:creditNote.qtyInvalid", { max }) });
          continue;
        }
        total += Number(raw);
      }
      if (!invalid && total === 0)
        ctx.addIssue({ code: "custom", path: ["qty"], message: vmsg("cashier:creditNote.chooseLines") });
    });
}

type Values = z.infer<ReturnType<typeof makeSchema>>;

/** Mounted only while open, so every opening starts with a fresh form. */
export function CreditNoteDialog(props: Parameters<typeof CreditNoteDialogOpen>[0]) {
  return props.open ? <CreditNoteDialogOpen {...props} /> : null;
}

/**
 * Draft a credit note of whole units of an approved invoice's lines (FEATURES 5.11). The
 * invoice itself never changes (invariant 2); a supervisor approves the note.
 */
function CreditNoteDialogOpen({
  invoice,
  open,
  onOpenChange,
}: {
  invoice: Invoice;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation(["cashier", "common", "errors"]);
  const translateError = useTranslateError();
  const names = useNames();
  const reasons = useReasons("credit_note", open);
  const create = useCreateCreditNote();
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const creditable = invoice.lines.filter((l) => l.quantity - l.credited_quantity > 0);
  const [schema] = useState(() =>
    makeSchema(Object.fromEntries(creditable.map((l) => [String(l.id), l.quantity - l.credited_quantity]))),
  );
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { reason: "", note: "", qty: {} } });
  const { t: tCommon } = useTranslation();
  // The "at least one unit" issue sits on `qty` itself; its type is the record's entries.
  const qtyRoot = form.formState.errors.qty as { message?: unknown } | undefined;
  const linesError = translateMessage(tCommon, typeof qtyRoot?.message === "string" ? qtyRoot.message : undefined);

  const submit = form.handleSubmit(async (v) => {
    setError(null);
    const lines = creditable
      .map((l) => ({ invoice_line_id: l.id, quantity: Number(normalizeAmountInput(v.qty[String(l.id)] ?? "")) }))
      .filter((l) => l.quantity > 0);
    try {
      await create.mutateAsync({ invoiceId: invoice.id, body: { lines, reason: v.reason, note: v.note } });
      setDone(true);
    } catch (e) {
      setError(translateError(e));
    }
  });

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!form.formState.isSubmitting) onOpenChange(next);
      }}
    >
      <DialogContent className="max-h-[90dvh] overflow-y-auto" data-testid="credit-note-dialog">
        <DialogHeader>
          <DialogTitle>{t("creditNote.title", { number: invoice.number ?? "" })}</DialogTitle>
          <DialogDescription>{t("creditNote.description")}</DialogDescription>
        </DialogHeader>
        {done ? (
          <>
            <AlertCard variant="success" title={t("creditNote.createdTitle")} live>
              {t("creditNote.createdBody")}
            </AlertCard>
            <DialogFooter>
              <Button
                onClick={() => {
                  onOpenChange(false);
                }}
              >
                {t("common:actions.close")}
              </Button>
            </DialogFooter>
          </>
        ) : (
          <Form {...form}>
            <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4">
              <fieldset className="grid gap-3">
                <legend className="mb-2 text-sm font-medium">{t("creditNote.lines")}</legend>
                {creditable.map((l) => {
                  const max = l.quantity - l.credited_quantity;
                  return (
                    <FormField
                      key={l.id}
                      control={form.control}
                      name={`qty.${String(l.id)}`}
                      render={({ field }) => (
                        <FormItem className="grid grid-cols-[1fr_6rem] items-center gap-x-3 gap-y-1">
                          <FormLabel className="flex min-w-0 flex-col items-start gap-0.5">
                            <span className="break-words">{names.name(l.service)}</span>
                            <span className="text-xs font-normal text-muted">
                              {t("creditNote.lineHint", { max })} · <MoneyText value={l.patient_share} />
                            </span>
                          </FormLabel>
                          <FormControl>
                            <Input
                              type="text"
                              inputMode="numeric"
                              autoComplete="off"
                              dir="ltr"
                              placeholder="0"
                              {...field}
                              data-testid={`credit-qty-${String(l.id)}`}
                            />
                          </FormControl>
                          <FormMessage className="col-span-2" />
                        </FormItem>
                      )}
                    />
                  );
                })}
                {linesError ? (
                  <p role="alert" className="text-xs font-medium text-danger-fg" data-testid="credit-lines-error">
                    {linesError}
                  </p>
                ) : null}
              </fieldset>
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
                  {t("creditNote.submit")}
                </Button>
              </DialogFooter>
            </form>
          </Form>
        )}
      </DialogContent>
    </Dialog>
  );
}
