import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useState, type ReactNode } from "react";
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
import { toApiError } from "@/lib/api/errors";
import { useTranslateError } from "@/lib/api/translate-error";
import { vmsg } from "@/lib/validation";

export interface ReasonOption {
  /** Reason code stored with the action (core.ReasonCode). */
  code: string;
  /** Localized label. */
  label: string;
}

export interface ReasonValue {
  code: string;
  note: string;
}

export interface ReasonDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  reasons: readonly ReasonOption[];
  confirmLabel?: ReactNode;
  destructive?: boolean;
  /** Free text is mandatory by default (FEATURES 4.2: list plus free text). */
  noteRequired?: boolean;
  /** May return a promise; errors are shown inside the dialog. */
  onSubmit: (value: ReasonValue) => void | Promise<void>;
  /** Extra content above the form, e.g. what is being cancelled. */
  children?: ReactNode;
}

const NOTE_MIN = 3;
const NOTE_MAX = 500;

function schemaFor(noteRequired: boolean) {
  return z.object({
    code: z.string().min(1, vmsg("validation.selectOption")),
    note: noteRequired
      ? z
          .string()
          .trim()
          .min(1, vmsg("validation.required"))
          .min(NOTE_MIN, vmsg("validation.minLength", { min: NOTE_MIN }))
          .max(NOTE_MAX)
      : z.string().trim().max(NOTE_MAX),
  });
}

/**
 * Collects the reason for an audited action (cancel, discount, refund,
 * override). The reason code and note go to the server together; the
 * server records approver and time (invariant 4).
 */
export function ReasonDialog({
  open,
  onOpenChange,
  title,
  description,
  reasons,
  confirmLabel,
  destructive = false,
  noteRequired = true,
  onSubmit,
  children,
}: ReasonDialogProps) {
  const { t } = useTranslation(["common", "errors"]);
  const translateError = useTranslateError();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<ReasonValue>({
    resolver: zodResolver(schemaFor(noteRequired)),
    defaultValues: { code: "", note: "" },
  });
  const { reset } = form;

  useEffect(() => {
    if (!open) reset({ code: "", note: "" });
  }, [open, reset]);

  const submit = form.handleSubmit(async (value) => {
    setError(null);
    try {
      await onSubmit({ code: value.code, note: value.note.trim() });
      onOpenChange(false);
    } catch (e) {
      setError(translateError(toApiError(e)));
    }
  });

  const pending = form.formState.isSubmitting;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (pending) return;
        if (!next) setError(null);
        onOpenChange(next);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description ?? t("reason.description")}</DialogDescription>
        </DialogHeader>
        {children}
        <Form {...form}>
          <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4">
            <SelectField
              control={form.control}
              name="code"
              label={t("reason.code")}
              placeholder={t("reason.codePlaceholder")}
              options={reasons.map((r) => ({ value: r.code, label: r.label }))}
              required
            />
            <TextareaField
              control={form.control}
              name="note"
              label={t("reason.note")}
              placeholder={t("reason.notePlaceholder")}
              required={noteRequired}
              rows={3}
              maxLength={NOTE_MAX}
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
                disabled={pending}
                onClick={() => {
                  onOpenChange(false);
                }}
              >
                {t("actions.cancel")}
              </Button>
              <Button type="submit" variant={destructive ? "destructive" : "default"} loading={pending}>
                {confirmLabel ?? t("reason.submit")}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
