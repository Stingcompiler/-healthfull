import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { AlertCard } from "@/components/AlertCard";
import { Form, SelectField, TextareaField } from "@/components/form";
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

import { useSetLinePayer } from "../api";
import { useNames } from "../lib/use-names";
import type { NameRef, ServiceLine } from "../types";

const CASH = "cash";

const schema = z.object({
  payer: z.string().min(1, vmsg("validation.selectOption")),
  note: z.string().trim().min(1, vmsg("validation.required")).max(500),
});

/** Mounted only while open, so every opening starts with a fresh form. */
export function LinePayerDialog(props: Parameters<typeof LinePayerDialogOpen>[0]) {
  return props.line !== null ? <LinePayerDialogOpen {...props} /> : null;
}

/** Bill one unbilled line to another payer of the patient, or to cash (FEATURES 5.6). */
function LinePayerDialogOpen({
  line,
  payers,
  onOpenChange,
}: {
  line: ServiceLine | null;
  payers: readonly NameRef[];
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation(["cashier", "common", "errors"]);
  const translateError = useTranslateError();
  const names = useNames();
  const save = useSetLinePayer();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<{ payer: string; note: string }>({
    resolver: zodResolver(schema),
    defaultValues: { payer: line?.payer ? String(line.payer.id) : CASH, note: "" },
  });

  const submit = form.handleSubmit(async (v) => {
    if (!line) return;
    setError(null);
    try {
      await save.mutateAsync({
        serviceLineId: line.id,
        payerId: v.payer === CASH ? null : Number(v.payer),
        note: v.note,
      });
      onOpenChange(false);
    } catch (e) {
      setError(translateError(e));
    }
  });

  return (
    <Dialog open={line !== null} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("linePayer.title")}</DialogTitle>
          <DialogDescription>{line ? names.name(line.service) : null}</DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4">
            <SelectField
              control={form.control}
              name="payer"
              label={t("linePayer.payer")}
              options={[
                { value: CASH, label: t("invoice.cash") },
                ...payers.map((p) => ({ value: String(p.id), label: names.name(p) })),
              ]}
              required
            />
            <TextareaField control={form.control} name="note" label={t("linePayer.note")} rows={2} required />
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
                {t("common:actions.save")}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
