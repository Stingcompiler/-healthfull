import { useState, type SyntheticEvent, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { useTranslateError } from "@/lib/api/translate-error";

import { ErrorAlert, LabeledField } from "./common";

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
 * A decision documented by a note (why an adjustment is rejected, why a sent transfer is
 * cancelled). The server stores the note with the decider and the time (invariant 4).
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
        {open ? <NoteForm onOpenChange={onOpenChange} {...rest} /> : null}
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
  const { t } = useTranslation(["pharmacy", "common"]);
  const translateError = useTranslateError();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [checked, setChecked] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const missing = noteRequired && !note.trim();

  const submit = async (e: SyntheticEvent) => {
    e.preventDefault();
    setChecked(true);
    setError(null);
    if (missing) return;
    setBusy(true);
    try {
      await onSubmit(note.trim());
      onOpenChange(false);
    } catch (err) {
      setError(translateError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4">
      <LabeledField label={label} required={noteRequired} error={checked && missing ? t("common.required") : null}>
        {(id, describedBy) => (
          <Textarea
            id={id}
            rows={3}
            maxLength={1000}
            value={note}
            aria-describedby={describedBy}
            data-testid="note-input"
            onChange={(e) => {
              setNote(e.target.value);
            }}
          />
        )}
      </LabeledField>
      <ErrorAlert message={error} />
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
        <Button
          type="submit"
          variant={destructive ? "destructive" : "default"}
          loading={busy}
          data-testid="note-confirm"
        >
          {confirmLabel}
        </Button>
      </DialogFooter>
    </form>
  );
}
