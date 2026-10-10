import { CheckCheck, Syringe } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { SearchInput } from "@/components/SearchInput";
import { Skeleton } from "@/components/ui/skeleton";
import { isApiError } from "@/lib/api/errors";
import { useTranslateError } from "@/lib/api/translate-error";
import { useLanguage } from "@/lib/i18n-hooks";
import { cn } from "@/lib/utils";

import { useMarkDone, useProceduresDone, useProcedureWorklist } from "../api";
import { DoneNoteDialog } from "../components/DoneNoteDialog";
import { NursingTabs } from "../components/NursingTabs";
import { ProcedureCard } from "../components/ProcedureCard";
import { QueryError } from "../components/QueryError";
import { nameOf, patientName } from "../lib";
import type { ProcedureLine } from "../types";
import { useUndoCommit } from "../use-undo-commit";

/** How long a "done" tap can be undone before it is sent (FEATURES 10.2). */
export const UNDO_WINDOW_MS = 5000;

/** The procedure desk (FEATURES 10.1, 10.2): paid or authorized procedures, one tap "done". */
export function NursingPage() {
  const { t } = useTranslation("nursing");
  const language = useLanguage();
  const translateError = useTranslateError();
  const [q, setQ] = useState("");
  const [department, setDepartment] = useState<number | null>(null);
  const [noteFor, setNoteFor] = useState<ProcedureLine | null>(null);
  const [saving, setSaving] = useState<ReadonlySet<number>>(() => new Set());
  const worklist = useProcedureWorklist(q, null);
  const done = useProceduresDone();
  const markDone = useMarkDone();
  const lines = useMemo(() => worklist.data ?? [], [worklist.data]);

  const commit = useCallback(
    (lineId: number, note: string) => {
      const line = lines.find((l) => l.id === lineId);
      const service = line ? nameOf(line.service, language) : "";
      setSaving((prev) => new Set(prev).add(lineId));
      markDone
        .mutateAsync({ lineId, note })
        .then(() => {
          toast.success(t("procedures.savedToast", { service }));
        })
        .catch((error: unknown) => {
          // Someone else was faster: the line is done, which is what the nurse wanted.
          if (isApiError(error) && error.code === "LINE_ALREADY_PERFORMED") toast.info(translateError(error));
          else toast.error(t("procedures.failedToast", { service, error: translateError(error) }));
        })
        .finally(() => {
          setSaving((prev) => {
            const next = new Set(prev);
            next.delete(lineId);
            return next;
          });
        });
    },
    [lines, language, markDone, t, translateError],
  );
  const undo = useUndoCommit<string>({ delayMs: UNDO_WINDOW_MS, commit });
  const waiting = undo.pending.size > 0;
  // Closing the tab inside the undo window would drop the tap: ask the browser to confirm.
  useEffect(() => {
    if (!waiting) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => {
      window.removeEventListener("beforeunload", warn);
    };
  }, [waiting]);

  const departments = useMemo(() => {
    const seen = new Map<number, NonNullable<ProcedureLine["department"]>>();
    for (const line of lines) if (line.department) seen.set(line.department.id, line.department);
    return [...seen.values()];
  }, [lines]);
  const shown = department === null ? lines : lines.filter((l) => l.department?.id === department);

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title={t("title")} description={t("procedures.description")} icon={<Syringe />} />
      <NursingTabs current="procedures" />

      <div className="flex flex-col gap-3 md:flex-row md:items-center">
        <SearchInput
          label={t("procedures.search")}
          placeholder={t("procedures.search")}
          onSearch={setQ}
          loading={worklist.isFetching && q !== ""}
          className="md:max-w-sm"
        />
        {departments.length > 1 ? (
          <div role="group" aria-label={t("procedures.departments")} className="flex flex-wrap gap-2">
            <Chip active={department === null} onClick={() => setDepartment(null)}>
              {t("procedures.allDepartments")}
            </Chip>
            {departments.map((d) => (
              <Chip key={d.id} active={department === d.id} onClick={() => setDepartment(d.id)}>
                {nameOf(d, language)}
              </Chip>
            ))}
          </div>
        ) : null}
      </div>

      <section aria-labelledby="procedures-waiting" className="flex flex-col gap-3">
        <h2 id="procedures-waiting" className="flex items-center gap-2 text-sm font-semibold text-fg-muted">
          {t("procedures.waitingHeading")}
          {worklist.data ? (
            <span className="rounded-full bg-primary-soft px-2 py-0.5 tabular text-xs text-primary-strong">
              {shown.length}
            </span>
          ) : null}
        </h2>
        {worklist.isError ? (
          <QueryError
            title={t("procedures.loadError")}
            error={worklist.error}
            onRetry={() => void worklist.refetch()}
            retrying={worklist.isFetching}
          />
        ) : worklist.isPending ? (
          <div className="grid gap-3 lg:grid-cols-2" aria-busy="true">
            <Skeleton className="h-52" />
            <Skeleton className="h-52" />
          </div>
        ) : shown.length === 0 ? (
          <EmptyState
            icon={<Syringe />}
            title={q ? t("procedures.noMatch") : t("procedures.emptyTitle")}
            description={q ? undefined : t("procedures.emptyDescription")}
          />
        ) : (
          <ul className="grid gap-3 lg:grid-cols-2">
            {shown.map((line) => (
              <li key={line.id} className="min-w-0">
                <ProcedureCard
                  line={line}
                  deadline={undo.pending.get(line.id)?.deadline}
                  undoWindowMs={UNDO_WINDOW_MS}
                  saving={saving.has(line.id)}
                  onDone={() => {
                    undo.schedule(line.id, "");
                  }}
                  onDoneWithNote={() => {
                    setNoteFor(line);
                  }}
                  onUndo={() => {
                    undo.undo(line.id);
                  }}
                  onSaveNow={() => {
                    undo.commitNow(line.id);
                  }}
                />
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="procedures-done" className="flex flex-col gap-3">
        <h2 id="procedures-done" className="text-sm font-semibold text-fg-muted">
          {t("procedures.doneHeading")}
        </h2>
        {done.isError ? (
          <QueryError
            title={t("procedures.loadError")}
            error={done.error}
            onRetry={() => void done.refetch()}
            retrying={done.isFetching}
          />
        ) : (done.data ?? []).length === 0 ? (
          <p className="text-sm text-muted">{done.isPending ? null : t("procedures.noneDone")}</p>
        ) : (
          <ul className="card-surface divide-y divide-border" data-testid="procedures-done">
            {(done.data ?? []).map((line) => (
              <li
                key={line.id}
                data-line-id={line.id}
                className="flex flex-col gap-1 px-4 py-3 sm:flex-row sm:items-center sm:gap-4"
              >
                <CheckCheck className="size-5 shrink-0 text-success-fg max-sm:hidden" aria-hidden="true" />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-pretty break-words text-fg">
                    {nameOf(line.service, language)}
                  </p>
                  <p className="text-xs text-pretty break-words text-muted">
                    {patientName(line.patient, language)} · <bdi>{line.patient.file_no}</bdi>
                    {line.performed_note ? ` · ${t("procedures.doneNote", { note: line.performed_note })}` : ""}
                  </p>
                </div>
                <p className="shrink-0 text-xs text-muted">
                  {line.performed_by
                    ? `${t("procedures.doneBy", { name: nameOf(line.performed_by, language) })} · `
                    : ""}
                  {line.performed_at ? <DateText value={line.performed_at} format="time" /> : null}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <DoneNoteDialog
        line={noteFor}
        onOpenChange={(open) => {
          if (!open) setNoteFor(null);
        }}
        onConfirm={(note) => {
          if (noteFor) undo.schedule(noteFor.id, note);
          setNoteFor(null);
        }}
      />
    </div>
  );
}

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "inline-flex h-11 items-center rounded-full border px-4 text-sm font-medium focus-ring",
        active
          ? "border-primary bg-primary-soft text-primary-strong"
          : "border-border-strong bg-surface text-fg hover:bg-accent",
      )}
    >
      {children}
    </button>
  );
}
