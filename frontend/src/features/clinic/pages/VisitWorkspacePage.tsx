import { Link, useParams } from "@tanstack/react-router";
import { CheckCheck, ClipboardList, FileText, FlaskConical, History, Megaphone, Play, Stethoscope } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { AlertCard } from "@/components/AlertCard";
import { Can } from "@/components/Can";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { EmptyState } from "@/components/EmptyState";
import { ArrowBack } from "@/components/icons";
import { KbdCombo } from "@/components/Kbd";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { UnsavedChangesGuard } from "@/components/UnsavedChangesGuard";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { isApiError } from "@/lib/api/errors";
import { useCurrentUser } from "@/lib/auth/hooks";
import { useTranslateError } from "@/lib/api/translate-error";
import { useShortcut } from "@/lib/hooks/use-shortcut";
import { useLanguage } from "@/lib/i18n-hooks";

import { useQueueAction, useWorkspace } from "../api";
import { HistoryTab } from "../components/HistoryTab";
import { NoteTab } from "../components/NoteTab";
import { OrdersTab } from "../components/OrdersTab";
import { QueryError } from "../components/QueryError";
import { QueueStatusBadge } from "../components/QueueStatusBadge";
import { ResultsTab } from "../components/ResultsTab";
import { SummaryPanel } from "../components/SummaryPanel";
import { patientName } from "../lib";

const TABS = ["note", "orders", "results", "history"] as const;
type Tab = (typeof TABS)[number];
const TAB_SHORTCUTS: Record<Tab, string> = { note: "alt+1", orders: "alt+2", results: "alt+3", history: "alt+4" };

/**
 * One visit as its doctor works on it (FEATURES 3.1-3.9): the patient summary beside tabs for
 * the note, orders, results and history. Two columns from lg (desktop and landscape tablet),
 * stacked below (portrait tablet and phone).
 */
export function VisitWorkspacePage() {
  const { t } = useTranslation("clinic");
  const language = useLanguage();
  const { visitId: rawId } = useParams({ strict: false });
  const visitId = Number(rawId);
  const valid = Number.isInteger(visitId) && visitId > 0;
  const workspace = useWorkspace(valid ? visitId : 0);
  const [tab, setTab] = useState<Tab>("note");
  // What would be lost by finishing now: unsaved note changes and unplaced draft orders. The note
  // and orders tabs stay mounted while hidden, so switching tabs never discards them.
  const [noteDirty, setNoteDirty] = useState(false);
  const [draftCount, setDraftCount] = useState(0);
  const me = useCurrentUser();

  useShortcut(
    Object.values(TAB_SHORTCUTS),
    (event) => {
      const found = TABS.find((name) => event.code === `Digit${TAB_SHORTCUTS[name].slice(-1)}`);
      if (found) setTab(found);
    },
    { allowInInputs: true },
  );

  if (!valid || (workspace.isError && isApiError(workspace.error) && workspace.error.status === 404)) {
    return (
      <div className="flex flex-col gap-5">
        <PageHeader title={t("workspace.notFoundTitle")} icon={<Stethoscope />} />
        <EmptyState
          title={t("workspace.notFoundTitle")}
          description={t("workspace.notFoundDescription")}
          action={
            <Button asChild variant="outline">
              <Link to="/clinic">{t("workspace.backToQueue")}</Link>
            </Button>
          }
        />
      </div>
    );
  }

  if (workspace.isError) {
    return (
      <div className="flex flex-col gap-5">
        <PageHeader title={t("workspace.title")} icon={<Stethoscope />} />
        <QueryError
          title={t("workspace.loadError")}
          error={workspace.error}
          onRetry={() => void workspace.refetch()}
          retrying={workspace.isFetching}
        />
      </div>
    );
  }

  if (workspace.isPending) {
    return (
      <div className="flex flex-col gap-5" aria-busy="true">
        <PageHeader title={t("workspace.title")} icon={<Stethoscope />} />
        <div className="grid gap-4 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)] xl:grid-cols-[minmax(0,24rem)_minmax(0,1fr)]">
          <Skeleton className="h-64" />
          <Skeleton className="h-96" />
        </div>
      </div>
    );
  }

  const ws = workspace.data;
  const open = ws.visit.status === "open";
  const name = patientName(ws.patient, language);
  const unsignedNote = ws.notes.some((n) => n.status === "draft" && n.author?.id === me?.id);

  return (
    <div className="flex flex-col gap-5">
      {/* A half-written note or unplaced draft orders are not lost by leaving the page. */}
      <UnsavedChangesGuard when={noteDirty || draftCount > 0} />
      <PageHeader
        eyebrow={
          <Link to="/clinic" className="inline-flex items-center gap-1 hover:text-fg hover:underline">
            <ArrowBack className="size-3.5" aria-hidden="true" />
            {t("workspace.backToQueue")}
          </Link>
        }
        // The patient's name and file number lead the summary card just below; the header names
        // the task instead of repeating them (the browser tab still carries the name).
        title={t("workspace.title")}
        documentTitle={`${t("workspace.title")} · ${name}`}
        description={
          <span className="inline-flex flex-wrap items-center gap-x-3 gap-y-1">
            <span>
              {t("workspace.visit")} <bdi className="tabular">{ws.visit.number}</bdi>
            </span>
            <span>{t(`visitType.${ws.visit.visit_type}`)}</span>
            {ws.queue_status ? <QueueStatusBadge status={ws.queue_status} /> : null}
            {!open ? <span className="font-medium text-warning-fg">{t(`visitStatus.${ws.visit.status}`)}</span> : null}
          </span>
        }
        icon={<Stethoscope />}
        actions={
          <QueueActions
            entryId={ws.queue_entry_id}
            status={ws.queue_status}
            pending={{ noteDirty, unsignedNote, draftCount }}
          />
        }
      />

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)] xl:grid-cols-[minmax(0,24rem)_minmax(0,1fr)]">
        <SummaryPanel workspace={ws} />

        <Tabs
          value={tab}
          onValueChange={(v) => {
            setTab(v as Tab);
          }}
          className="min-w-0"
        >
          <TabsList className="w-full" aria-label={t("workspace.tabsLabel")}>
            <TabsTrigger value="note" data-testid="tab-note" title={t("workspace.shortcutHint", { keys: "Alt+1" })}>
              <FileText aria-hidden="true" className="max-sm:hidden" />
              {t("tabs.note")}
            </TabsTrigger>
            <TabsTrigger value="orders" data-testid="tab-orders" title={t("workspace.shortcutHint", { keys: "Alt+2" })}>
              <ClipboardList aria-hidden="true" className="max-sm:hidden" />
              {t("tabs.orders")}
            </TabsTrigger>
            <TabsTrigger
              value="results"
              data-testid="tab-results"
              title={t("workspace.shortcutHint", { keys: "Alt+3" })}
            >
              <FlaskConical aria-hidden="true" className="max-sm:hidden" />
              {t("tabs.results")}
            </TabsTrigger>
            <TabsTrigger
              value="history"
              data-testid="tab-history"
              title={t("workspace.shortcutHint", { keys: "Alt+4" })}
            >
              <History aria-hidden="true" className="max-sm:hidden" />
              {t("tabs.history")}
            </TabsTrigger>
          </TabsList>
          <TabsContent value="note" forceMount className="data-[state=inactive]:hidden">
            <NoteTab workspace={ws} onDirtyChange={setNoteDirty} />
          </TabsContent>
          <TabsContent value="orders" forceMount className="data-[state=inactive]:hidden">
            <OrdersTab
              visitId={ws.visit.id}
              patientId={ws.patient.id}
              open={open}
              active={tab === "orders"}
              onDraftChange={setDraftCount}
            />
          </TabsContent>
          <TabsContent value="results">
            <ResultsTab patientId={ws.patient.id} active={tab === "results"} />
          </TabsContent>
          <TabsContent value="history">
            <HistoryTab patientId={ws.patient.id} currentVisitId={ws.visit.id} active={tab === "history"} />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}

interface Pending {
  noteDirty: boolean;
  unsignedNote: boolean;
  draftCount: number;
}

function QueueActions({
  entryId,
  status,
  pending,
}: {
  entryId: number | null;
  status: string | null;
  pending: Pending;
}) {
  const { t } = useTranslation("clinic");
  const action = useQueueAction();
  const translateError = useTranslateError();
  const [confirming, setConfirming] = useState(false);
  if (entryId === null || status === null) return null;

  const run = (move: "call" | "start" | "complete") =>
    action.mutateAsync({ entryId, action: move }).then(
      (moved) => {
        toast.success(t(`queue.movedToast.${moved.status === "done" ? "done" : "moved"}`));
      },
      (error: unknown) => {
        toast.error(translateError(error));
        throw error;
      },
    );

  return (
    <Can permission="visits.manage_queue">
      {status === "waiting" || status === "called" ? (
        <Button
          variant="default"
          loading={action.isPending}
          onClick={() => void run(status === "waiting" ? "call" : "start").catch(() => undefined)}
          data-testid="queue-start"
        >
          {status === "waiting" ? <Megaphone aria-hidden="true" /> : <Play aria-hidden="true" />}
          {status === "waiting" ? t("queue.call") : t("queue.start")}
        </Button>
      ) : null}
      {status === "in_progress" ? (
        <>
          <Button variant="default" onClick={() => setConfirming(true)} data-testid="queue-complete">
            <CheckCheck aria-hidden="true" />
            {t("queue.complete")}
            <KbdCombo combo="alt+enter" className="max-md:hidden" />
          </Button>
          <CompleteShortcut onTrigger={() => setConfirming(true)} />
          <ConfirmDialog
            open={confirming}
            onOpenChange={setConfirming}
            title={t("queue.completeTitle")}
            description={t("queue.completeDescription")}
            confirmLabel={t("queue.complete")}
            onConfirm={() => run("complete")}
          >
            {pending.noteDirty || pending.unsignedNote || pending.draftCount > 0 ? (
              <div data-testid="complete-pending">
                <AlertCard variant="warning" title={t("queue.unsavedTitle")}>
                  <ul className="list-disc ps-5">
                    {pending.noteDirty ? <li>{t("queue.unsavedNote")}</li> : null}
                    {pending.unsignedNote ? <li>{t("queue.unsignedNote")}</li> : null}
                    {pending.draftCount > 0 ? (
                      <li>{t("queue.unplacedOrders", { count: pending.draftCount })}</li>
                    ) : null}
                  </ul>
                </AlertCard>
              </div>
            ) : null}
          </ConfirmDialog>
        </>
      ) : null}
    </Can>
  );
}

function CompleteShortcut({ onTrigger }: { onTrigger: () => void }) {
  useShortcut("alt+enter", onTrigger, { allowInInputs: true });
  return null;
}
