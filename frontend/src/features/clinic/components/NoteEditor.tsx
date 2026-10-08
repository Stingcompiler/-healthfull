import { FileSignature, FileText, Save } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { AlertCard } from "@/components/AlertCard";
import { Can } from "@/components/Can";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { DateText } from "@/components/DateText";
import { Form, TextareaField } from "@/components/form";
import { KbdCombo } from "@/components/Kbd";
import { Button } from "@/components/ui/button";
import { useTranslateError } from "@/lib/api/translate-error";
import { useCurrentUser } from "@/lib/auth/hooks";
import { usePermission } from "@/lib/auth/hooks";
import { useShortcut } from "@/lib/hooks/use-shortcut";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

import { useCreateNote, useSignNote, useUpdateNote } from "../api";
import type { Note } from "../types";

const FIELDS = ["complaint", "history", "examination", "assessment", "plan"] as const;
type Values = Record<(typeof FIELDS)[number], string>;
const EMPTY: Values = { complaint: "", history: "", examination: "", assessment: "", plan: "" };

function valuesOf(note: Note | undefined): Values {
  if (!note) return EMPTY;
  return {
    complaint: note.complaint,
    history: note.history,
    examination: note.examination,
    assessment: note.assessment,
    plan: note.plan,
  };
}

/**
 * The doctor's clinical note (FEATURES 3.3): a draft the author edits until it is signed; a
 * signed note never changes (a correction is a new note).
 */
export function NoteEditor({
  visitId,
  notes,
  open,
  onDirtyChange,
}: {
  visitId: number;
  notes: readonly Note[];
  open: boolean;
  /** Tells the page whether typed text is unsaved (finishing the consultation warns about it). */
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const { t } = useTranslation("clinic");
  const me = useCurrentUser();
  const canWrite = usePermission("clinical.write_note") && open;
  const draft = notes.find((n) => n.status === "draft" && n.author?.id === me?.id);
  const others = notes.filter((n) => n !== draft);
  const create = useCreateNote(visitId);
  const update = useUpdateNote(visitId);
  const sign = useSignNote(visitId);
  const translateError = useTranslateError();
  const [error, setError] = useState<string | null>(null);
  const [confirmSign, setConfirmSign] = useState(false);

  const form = useForm<Values>({ defaultValues: valuesOf(draft) });
  const draftId = draft?.id;
  useEffect(() => {
    form.reset(valuesOf(draft));
    // Reset only when another draft is loaded, not on every refetch of the same one.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftId]);

  const save = async (values: Values): Promise<Note> => {
    setError(null);
    const saved = draftId ? await update.mutateAsync({ id: draftId, body: values }) : await create.mutateAsync(values);
    form.reset(values);
    return saved;
  };

  const onSave = form.handleSubmit(async (values) => {
    try {
      await save(values);
      toast.success(t("note.savedToast"));
    } catch (e) {
      setError(translateError(e));
    }
  });

  const onSign = async () => {
    const saved = await save(form.getValues());
    await sign.mutateAsync(saved.id);
    form.reset(EMPTY);
    toast.success(t("note.signedToast"));
  };

  useShortcut("mod+s", () => void onSave(), { enabled: canWrite, allowInInputs: true });

  const dirty = form.formState.isDirty;
  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);

  const watched = useWatch({ control: form.control });
  const empty = FIELDS.every((f) => !(watched[f] ?? "").trim());

  return (
    <section aria-labelledby="note-heading" className="card-surface flex flex-col gap-4 p-4 md:p-5">
      <div className="flex flex-wrap items-center gap-2">
        <FileText className="size-4 text-muted" aria-hidden="true" />
        <h2 id="note-heading" className="text-base font-semibold text-fg">
          {t("note.title")}
        </h2>
        {draft ? <span className="text-xs text-muted">{t("note.draft")}</span> : null}
      </div>

      {others.length > 0 ? (
        <ul className="flex flex-col gap-2">
          {others.map((n) => (
            <SignedNote key={n.id} note={n} />
          ))}
        </ul>
      ) : null}

      {canWrite ? (
        <Form {...form}>
          <form onSubmit={(e) => void onSave(e)} className="flex flex-col gap-3" data-testid="note-form">
            <div className="grid gap-3 md:grid-cols-2">
              <TextareaField control={form.control} name="complaint" label={t("note.complaint")} />
              <TextareaField control={form.control} name="history" label={t("note.history")} />
              <TextareaField control={form.control} name="examination" label={t("note.examination")} />
              <TextareaField control={form.control} name="assessment" label={t("note.assessment")} />
              <TextareaField control={form.control} name="plan" label={t("note.plan")} className="md:col-span-2" />
            </div>
            {error ? (
              <AlertCard variant="danger" live title={t("note.saveError")}>
                {error}
              </AlertCard>
            ) : null}
            <div className="flex flex-wrap items-center justify-end gap-2">
              <Button
                type="submit"
                variant="outline"
                loading={create.isPending || update.isPending}
                disabled={empty && !draftId}
                data-testid="note-save"
              >
                <Save aria-hidden="true" />
                {t("note.save")}
                <KbdCombo combo="mod+s" className="max-md:hidden" />
              </Button>
              <Button type="button" onClick={() => setConfirmSign(true)} disabled={empty} data-testid="note-sign">
                <FileSignature aria-hidden="true" />
                {t("note.sign")}
              </Button>
            </div>
          </form>
        </Form>
      ) : others.length === 0 ? (
        <p className="text-sm text-muted">{t("note.none")}</p>
      ) : null}

      <Can permission="clinical.write_note">
        <ConfirmDialog
          open={confirmSign}
          onOpenChange={setConfirmSign}
          title={t("note.signTitle")}
          description={t("note.signDescription")}
          confirmLabel={t("note.sign")}
          onConfirm={onSign}
        />
      </Can>
    </section>
  );
}

function SignedNote({ note }: { note: Note }) {
  const { t } = useTranslation("clinic");
  const language = useLanguage();
  return (
    <li className="rounded-control border border-border bg-subtle p-3 text-sm" data-testid="signed-note">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
        <span>
          {note.author ? pickName({ ar: note.author.name_ar, en: note.author.name_en }, language) : ""}
          {" · "}
          {note.status === "signed" ? t("note.signed") : t("note.draftOther")}
        </span>
        <DateText value={note.signed_at ?? note.updated_at} format="datetime" />
      </div>
      <dl className="grid gap-1.5">
        {FIELDS.map((f) =>
          note[f] ? (
            <div key={f} className="flex min-w-0 flex-col sm:flex-row sm:gap-2">
              <dt className="shrink-0 text-xs font-medium text-muted sm:w-28">{t(`note.${f}`)}</dt>
              <dd className="min-w-0 break-words whitespace-pre-line text-fg">{note[f]}</dd>
            </div>
          ) : null,
        )}
      </dl>
    </li>
  );
}
