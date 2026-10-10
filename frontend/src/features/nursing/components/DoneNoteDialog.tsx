import { Check } from "lucide-react";
import { useState } from "react";
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
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useLanguage } from "@/lib/i18n-hooks";

import { nameOf, patientName } from "../lib";
import type { ProcedureLine } from "../types";

const NOTE_MAX = 500;

/** "Done" with an optional note: the note goes with the mark (who and when are recorded). */
export function DoneNoteDialog({
  line,
  onOpenChange,
  onConfirm,
}: {
  line: ProcedureLine | null;
  onOpenChange: (open: boolean) => void;
  onConfirm: (note: string) => void;
}) {
  const { t } = useTranslation("nursing");
  const { t: tc } = useTranslation();
  const language = useLanguage();
  const [note, setNote] = useState("");

  return (
    <Dialog
      open={line !== null}
      onOpenChange={(open) => {
        if (!open) setNote("");
        onOpenChange(open);
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("procedures.noteDialog.title")}</DialogTitle>
          {line ? (
            <DialogDescription>
              {t("procedures.noteDialog.description", {
                service: nameOf(line.service, language),
                name: patientName(line.patient, language),
              })}
            </DialogDescription>
          ) : null}
        </DialogHeader>
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            onConfirm(note.trim());
            setNote("");
          }}
        >
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="done-note">{t("procedures.noteDialog.label")}</Label>
            <Textarea
              id="done-note"
              value={note}
              maxLength={NOTE_MAX}
              rows={3}
              placeholder={t("procedures.noteDialog.placeholder")}
              onChange={(e) => {
                setNote(e.target.value);
              }}
              autoFocus
            />
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                onOpenChange(false);
              }}
            >
              {tc("actions.cancel")}
            </Button>
            <Button type="submit" data-testid="procedure-note-confirm">
              <Check aria-hidden="true" />
              {t("procedures.noteDialog.confirm")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
