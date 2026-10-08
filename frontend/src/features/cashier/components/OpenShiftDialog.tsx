import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { AlertCard } from "@/components/AlertCard";
import { Form, SelectField, TextField } from "@/components/form";
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

import { useOpenShift, useTills } from "../api";
import { isAmount, normalizeAmountInput } from "../lib/money";
import { useNames } from "../lib/use-names";

const NO_TILL = "-";

const schema = z.object({
  openingFloat: z
    .string()
    .trim()
    .min(1, vmsg("validation.required"))
    .refine(isAmount, vmsg("cashier:validation.amount")),
  till: z.string(),
});

type Values = z.infer<typeof schema>;

/** Open the user's shift with an opening float (FEATURES 7.1). */
export function OpenShiftDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { t } = useTranslation(["cashier", "common", "errors"]);
  const translateError = useTranslateError();
  const names = useNames();
  const tills = useTills(open);
  const openShift = useOpenShift();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { openingFloat: "0", till: NO_TILL } });
  const { reset } = form;
  useEffect(() => {
    if (open) {
      reset({ openingFloat: "0", till: NO_TILL });
      setError(null);
    }
  }, [open, reset]);

  const submit = form.handleSubmit(async (v) => {
    setError(null);
    try {
      await openShift.mutateAsync({
        opening_float: normalizeAmountInput(v.openingFloat),
        till: v.till === NO_TILL ? null : v.till,
        note: "",
      });
      onOpenChange(false);
    } catch (e) {
      setError(translateError(e));
    }
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="open-shift-dialog">
        <DialogHeader>
          <DialogTitle>{t("shift.openTitle")}</DialogTitle>
          <DialogDescription>{t("shift.openDescription")}</DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4">
            <TextField
              control={form.control}
              name="openingFloat"
              label={t("shift.openingFloat")}
              inputMode="decimal"
              dir="ltr"
              autoFocus
              required
            />
            <SelectField
              control={form.control}
              name="till"
              label={t("shift.till")}
              options={[
                { value: NO_TILL, label: t("shift.noTill") },
                ...(tills.data ?? []).map((x) => ({ value: x.code, label: names.name(x) })),
              ]}
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
              <Button type="submit" loading={form.formState.isSubmitting} data-testid="open-shift-submit">
                {t("shift.open")}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
