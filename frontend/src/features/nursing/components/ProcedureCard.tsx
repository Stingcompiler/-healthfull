import { Check, MessageSquarePlus, ShieldAlert, Undo2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { DateText } from "@/components/DateText";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ageFromBirthDate } from "@/lib/age";
import { useLanguage } from "@/lib/i18n-hooks";
import { cn } from "@/lib/utils";

import { nameOf, patientName } from "../lib";
import type { ProcedureLine } from "../types";
import { useSecondsLeft } from "../use-undo-commit";
import { AllergyChips } from "./AllergyChips";

/**
 * One waiting procedure on a tablet: what to give, to whom (allergies prominent), and a large
 * "Done" target. After the tap the card shows the undo window until the mark is sent.
 */
export function ProcedureCard({
  line,
  deadline,
  undoWindowMs,
  saving,
  onDone,
  onDoneWithNote,
  onUndo,
  onSaveNow,
}: {
  line: ProcedureLine;
  /** Set while the undo window runs. */
  deadline: number | undefined;
  undoWindowMs: number;
  saving: boolean;
  onDone: () => void;
  onDoneWithNote: () => void;
  onUndo: () => void;
  onSaveNow: () => void;
}) {
  const { t } = useTranslation("nursing");
  const { t: tc } = useTranslation();
  const language = useLanguage();
  const seconds = useSecondsLeft(deadline, undoWindowMs);
  const who = patientName(line.patient, language);
  const service = nameOf(line.service, language);
  const age = line.patient.date_of_birth ? ageFromBirthDate(line.patient.date_of_birth) : null;
  const waiting = deadline !== undefined;

  return (
    <article
      data-testid="procedure-card"
      data-line-id={line.id}
      data-file-no={line.patient.file_no}
      aria-busy={saving || undefined}
      className={cn(
        "card-surface flex min-w-0 flex-col gap-3 p-4 md:p-5",
        waiting && "border-success-border bg-success-bg/40",
      )}
    >
      <div className="flex min-w-0 flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-lg leading-snug font-semibold text-pretty break-words text-fg">{service}</h3>
          <p className="mt-0.5 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
            {line.department ? <span>{nameOf(line.department, language)}</span> : null}
            {line.quantity > 1 ? (
              <span className="font-semibold text-fg">{t("procedures.quantity", { quantity: line.quantity })}</span>
            ) : null}
            <span>
              {t("procedures.orderedAt")} <DateText value={line.ordered_at} format="time" />
            </span>
            {line.ordered_by ? (
              <span>{t("procedures.orderedBy", { name: nameOf(line.ordered_by, language) })}</span>
            ) : null}
          </p>
        </div>
        {line.authorized ? (
          <Badge variant="warning">
            <ShieldAlert aria-hidden="true" />
            {t("procedures.authorized")}
          </Badge>
        ) : null}
      </div>

      <div className="flex min-w-0 flex-col gap-1.5 rounded-control bg-subtle px-3 py-2">
        <p className="text-base font-semibold text-pretty break-words text-fg">{who}</p>
        <p className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
          <span>
            {tc("patient.fileNo")} <bdi className="tabular font-semibold text-fg">{line.patient.file_no}</bdi>
          </span>
          {age ? (
            <span>
              {age.years >= 1 ? tc("patient.years", { count: age.years }) : tc("patient.months", { count: age.months })}
            </span>
          ) : null}
          <span>{tc(`sex.${line.patient.sex}`)}</span>
        </p>
        <AllergyChips allergies={line.allergies} />
      </div>

      {line.note ? (
        <p className="text-sm text-pretty break-words text-fg">{t("procedures.orderNote", { note: line.note })}</p>
      ) : null}

      {waiting ? (
        <div className="flex flex-wrap items-center gap-2" role="status">
          <p className="me-auto flex items-center gap-2 text-sm font-medium text-success-fg">
            <Check className="size-5" aria-hidden="true" />
            {saving ? t("procedures.saving") : t("procedures.pending", { seconds })}
          </p>
          <Button variant="ghost" onClick={onSaveNow} disabled={saving}>
            {t("procedures.saveNow")}
          </Button>
          <Button
            variant="outline"
            size="lg"
            className="h-14 min-w-32"
            onClick={onUndo}
            disabled={saving}
            aria-label={t("procedures.undoNamed", { name: who })}
            data-testid="procedure-undo"
          >
            <Undo2 className="size-5 rtl:-scale-x-100" aria-hidden="true" />
            {t("procedures.undo")}
          </Button>
        </div>
      ) : (
        <div className="flex flex-wrap items-center justify-end gap-2">
          <Button
            variant="outline"
            className="h-14 px-4"
            onClick={onDoneWithNote}
            aria-label={t("procedures.withNoteNamed", { service, name: who })}
          >
            <MessageSquarePlus className="size-5" aria-hidden="true" />
            {t("procedures.withNote")}
          </Button>
          <Button
            size="lg"
            className="h-14 min-w-36 grow text-lg sm:grow-0"
            onClick={onDone}
            aria-label={t("procedures.doneNamed", { service, name: who })}
            data-testid="procedure-done"
          >
            <Check className="size-6" aria-hidden="true" />
            {t("procedures.done")}
          </Button>
        </div>
      )}
    </article>
  );
}
