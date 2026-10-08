import { zodResolver } from "@hookform/resolvers/zod";
import { useState, type ReactNode } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { AlertCard } from "@/components/AlertCard";
import { Form, TextareaField } from "@/components/form";
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

const required = z.object({ note: z.string().trim().min(1, vmsg("validation.required")).max(1000) });
const optional = z.object({ note: z.string().trim().max(1000) });

interface NoteDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description: ReactNode;
  label: ReactNode;
  confirmLabel: ReactNode;
  destructive?: boolean;
  noteRequired?: boolean;
  onSubmit: (note: string) => Promise<unknown>;
  children?: ReactNode;
  testId?: string;
}

/**
 * A decision documented by a note (what was checked, why a draft is voided...). The server
 * stores the note with the approver and the time (invariant 4).
 */
export function NoteDialog({ open, onOpenChange, title, description, children, testId, ...rest }: NoteDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid={testId}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        {children}
        {/* Mounted only while open, so every opening starts with an empty form. */}
        <NoteForm onOpenChange={onOpenChange} {...rest} />
      </DialogContent>
    </Dialog>
  );
}

function NoteForm({
  onOpenChange,
  label,
  confirmLabel,
  destructive = false,
  noteRequired = true,
  onSubmit,
}: Pick<NoteDialogProps, "onOpenChange" | "label" | "confirmLabel" | "destructive" | "noteRequired" | "onSubmit">) {
  const { t } = useTranslation(["common", "errors"]);
  const translateError = useTranslateError();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<{ note: string }>({
    resolver: zodResolver(noteRequired ? required : optional),
    defaultValues: { note: "" },
  });

  const submit = form.handleSubmit(async ({ note }) => {
    setError(null);
    try {
      await onSubmit(note.trim());
      onOpenChange(false);
    } catch (e) {
      setError(translateError(e));
    }
  });

  return (
    <Form {...form}>
      <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4">
        <TextareaField control={form.control} name="note" label={label} required={noteRequired} rows={3} maxLength={1000} />
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
            {t("actions.cancel")}
          </Button>
          <Button type="submit" variant={destructive ? "destructive" : "default"} loading={form.formState.isSubmitting}>
            {confirmLabel}
          </Button>
        </DialogFooter>
      </form>
    </Form>
  );
}
