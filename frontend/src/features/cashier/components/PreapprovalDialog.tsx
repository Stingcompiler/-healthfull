import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { AlertCard } from "@/components/AlertCard";
import { Form, TextField } from "@/components/form";
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

import { useSetPreapproval } from "../api";
import type { InvoiceLine } from "../types";

const schema = z.object({ reference: z.string().trim().min(1, vmsg("validation.required")).max(100) });

/** The payer's pre-approval number on a draft line that requires one (FEATURES 5.8). */
export function PreapprovalDialog({
  invoiceId,
  line,
  onOpenChange,
}: {
  invoiceId: number;
  line: InvoiceLine | null;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation(["cashier", "common", "errors"]);
  const translateError = useTranslateError();
  const save = useSetPreapproval();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<{ reference: string }>({ resolver: zodResolver(schema), defaultValues: { reference: "" } });
  const { reset } = form;
  const open = line !== null;
  useEffect(() => {
    if (line) {
      reset({ reference: line.pre_approval_ref });
      setError(null);
    }
  }, [line, reset]);

  const submit = form.handleSubmit(async ({ reference }) => {
    if (!line) return;
    setError(null);
    try {
      await save.mutateAsync({ invoiceId, lineId: line.id, reference: reference.trim() });
      onOpenChange(false);
    } catch (e) {
      setError(translateError(e));
    }
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("preapproval.title")}</DialogTitle>
          <DialogDescription>{t("preapproval.description")}</DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4">
            <TextField control={form.control} name="reference" label={t("preapproval.reference")} dir="ltr" required />
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
