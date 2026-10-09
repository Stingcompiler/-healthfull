import { NotebookPen, Plus } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { AlertCard } from "@/components/AlertCard";
import { DateText } from "@/components/DateText";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useTranslateError } from "@/lib/api/translate-error";
import { usePermission } from "@/lib/auth/hooks";
import { useLanguage } from "@/lib/i18n-hooks";

import { useAddNursingNote } from "../api";
import { nameOf } from "../lib";
import type { NursingNote, NursingNoteKind } from "../types";

const KINDS: readonly NursingNoteKind[] = ["general", "procedure", "handover"];
const NOTE_MAX = 4000;

/** Nursing notes of the visit (FEATURES 10.3): add one, read them newest first. */
export function NursingNotesPanel({
  visitId,
  notes,
  writable,
}: {
  visitId: number;
  notes: readonly NursingNote[];
  writable: boolean;
}) {
  const { t } = useTranslation("nursing");
  const language = useLanguage();
  const canWrite = usePermission("clinical.write_nursing_note") && writable;
  const add = useAddNursingNote(visitId);
  const translateError = useTranslateError();
  const [text, setText] = useState("");
  const [kind, setKind] = useState<NursingNoteKind>("general");
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    setError(null);
    add.mutate(
      { text: text.trim(), kind },
      {
        onSuccess: () => {
          setText("");
          setKind("general");
          toast.success(t("notes.savedToast"));
        },
        onError: (e) => {
          setError(translateError(e));
        },
      },
    );
  };

  return (
    <section aria-labelledby="nursing-notes" className="card-surface flex flex-col gap-4 p-4 md:p-5">
      <h2 id="nursing-notes" className="flex items-center gap-2 text-base font-semibold text-fg">
        <NotebookPen className="size-4 text-muted" aria-hidden="true" />
        {t("notes.title")}
      </h2>
      {canWrite ? (
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (text.trim()) submit();
          }}
        >
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="nursing-note-text">{t("notes.label")}</Label>
            <Textarea
              id="nursing-note-text"
              value={text}
              rows={3}
              maxLength={NOTE_MAX}
              placeholder={t("notes.placeholder")}
              onChange={(e) => {
                setText(e.target.value);
              }}
            />
          </div>
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div className="flex min-w-40 flex-col gap-1.5">
              <Label htmlFor="nursing-note-kind">{t("notes.kind")}</Label>
              <Select
                value={kind}
                onValueChange={(v) => {
                  setKind(v as NursingNoteKind);
                }}
              >
                <SelectTrigger id="nursing-note-kind" className="h-12">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {KINDS.map((k) => (
                    <SelectItem key={k} value={k}>
                      {t(`notes.kinds.${k}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Button
              type="submit"
              size="lg"
              className="h-12 max-sm:w-full"
              loading={add.isPending}
              disabled={!text.trim()}
              data-testid="nursing-note-add"
            >
              <Plus aria-hidden="true" />
              {t("notes.add")}
            </Button>
          </div>
          {error ? (
            <AlertCard variant="danger" live title={t("notes.saveError")}>
              {error}
            </AlertCard>
          ) : null}
        </form>
      ) : null}
      {notes.length === 0 ? (
        <p className="text-sm text-muted">{t("notes.none")}</p>
      ) : (
        <ul className="flex flex-col gap-2" data-testid="nursing-notes">
          {notes.map((n) => (
            <li key={n.id} className="rounded-control border border-border px-3 py-2">
              <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-muted">
                <Badge variant="neutral">{t(`notes.kinds.${n.kind}`)}</Badge>
                <span>{n.author ? nameOf(n.author, language) : null}</span>
                <span className="ms-auto">
                  <DateText value={n.created_at} format="datetime" />
                </span>
              </div>
              <p className="text-sm text-pretty break-words whitespace-pre-line text-fg">{n.text}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
