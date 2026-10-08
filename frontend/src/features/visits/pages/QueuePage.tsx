import { Link, useNavigate } from "@tanstack/react-router";
import type { ColumnDef } from "@tanstack/react-table";
import {
  Ban,
  CircleCheck,
  ListOrdered,
  Megaphone,
  MonitorPlay,
  Plus,
  Printer,
  RotateCcw,
  Stethoscope,
  UserRound,
  UserX,
} from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Can } from "@/components/Can";
import { DataTable, DataTableOpenButton, type DataTableRowAction } from "@/components/DataTable";
import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { KpiCard } from "@/components/KpiCard";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { patientName } from "@/features/patients/lib";
import { toApiError } from "@/lib/api/errors";
import { useTranslateError } from "@/lib/api/translate-error";
import { usePermission } from "@/lib/auth/hooks";
import { formatNumber } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

import { useBoard, useCallNext, useMoveQueueEntry, useVisitOptions } from "../api";
import { CancelVisitDialog } from "../components/CancelVisitDialog";
import { CreateVisitDialog } from "../components/CreateVisitDialog";
import { FeeBadge, QueueStatusBadge } from "../components/QueueBadges";
import { TokenSlipDialog } from "../components/TokenSlipDialog";
import { ALL, useDeviceChoice } from "../lib";
import type { QueueAction, QueueRow } from "../types";

/** Reception board per clinic (FEATURES 2.3): today's tokens, call next, token print, cancel. */
export function QueuePage() {
  const { t } = useTranslation(["visits", "common"]);
  const language = useLanguage();
  const navigate = useNavigate();
  const translateError = useTranslateError();
  const options = useVisitOptions();
  const [departmentId, setDepartmentId] = useDeviceChoice("boardDepartment");
  const [showFinished, setShowFinished] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [tokenEntry, setTokenEntry] = useState<number | null>(null);
  const [cancelling, setCancelling] = useState<{ id: number; number: string } | null>(null);
  const board = useBoard(departmentId, showFinished);
  const callNext = useCallNext();
  const move = useMoveQueueEntry();
  const canManage = usePermission("visits.manage_queue");
  const canCancel = usePermission("visits.cancel");
  const rows = board.data ?? [];
  const n = (value: number) => formatNumber(value, language);

  const departments = options.data?.departments ?? [];
  const department = departments.find((d) => d.id === departmentId) ?? null;

  const act = async (row: QueueRow, action: QueueAction) => {
    try {
      await move.mutateAsync({ entryId: row.id, action });
      toast.success(t(`board.done.${action}`, { token: n(row.token_no) }));
    } catch (e) {
      toast.error(translateError(toApiError(e)));
    }
  };

  const onCallNext = async () => {
    if (departmentId === null) return;
    try {
      const called = await callNext.mutateAsync(departmentId);
      toast.success(t("board.calledToken", { token: n(called.token_no), name: patientName(called.patient, language) }));
    } catch (e) {
      toast.error(translateError(toApiError(e)));
    }
  };

  const actionsFor = (row: QueueRow): DataTableRowAction[] => {
    const out: DataTableRowAction[] = [];
    if (canManage) {
      if (row.status === "waiting")
        out.push({
          label: t("board.action.call"),
          icon: <Megaphone />,
          onSelect: () => void act(row, "call"),
          disabled: !row.ready,
        });
      if (row.status === "waiting" || row.status === "called")
        out.push({
          label: t("board.action.start"),
          icon: <Stethoscope />,
          onSelect: () => void act(row, "start"),
          disabled: !row.ready,
        });
      if (row.status === "in_progress")
        out.push({ label: t("board.action.finish"), icon: <CircleCheck />, onSelect: () => void act(row, "finish") });
      if (row.status === "called" || row.status === "no_show")
        out.push({ label: t("board.action.requeue"), icon: <RotateCcw />, onSelect: () => void act(row, "requeue") });
      if (row.status === "waiting" || row.status === "called")
        out.push({ label: t("board.action.no_show"), icon: <UserX />, onSelect: () => void act(row, "no_show") });
    }
    out.push({
      label: t("board.action.print"),
      icon: <Printer />,
      onSelect: () => {
        setTokenEntry(row.id);
      },
      separated: out.length > 0,
    });
    out.push({
      label: t("board.action.openFile"),
      icon: <UserRound />,
      onSelect: () => {
        void navigate({ to: "/patients/$patientId", params: { patientId: String(row.patient.id) } });
      },
    });
    if (canCancel && row.status !== "done" && row.status !== "in_progress") {
      out.push({
        label: t("board.action.cancelVisit"),
        icon: <Ban />,
        destructive: true,
        separated: true,
        onSelect: () => {
          setCancelling({ id: row.visit_id, number: row.visit_number });
        },
      });
    }
    return out;
  };

  const columns = useMemo<ColumnDef<QueueRow>[]>(
    () => [
      {
        id: "token",
        header: t("board.token"),
        meta: { label: t("board.token"), className: "w-20" },
        accessorKey: "token_no",
        cell: ({ row }) => <span className="tabular text-lg font-bold text-fg">{n(row.original.token_no)}</span>,
      },
      {
        id: "patient",
        header: t("board.patient"),
        meta: { label: t("board.patient") },
        accessorFn: (r) => patientName(r.patient, language),
        cell: ({ row }) => (
          <span className="flex min-w-0 flex-col">
            <span className="font-medium break-words">{patientName(row.original.patient, language)}</span>
            <bdi className="tabular text-xs text-muted">{row.original.patient.file_no}</bdi>
          </span>
        ),
      },
      {
        id: "doctor",
        header: t("board.doctor"),
        meta: { label: t("board.doctor") },
        enableSorting: false,
        cell: ({ row }) =>
          row.original.doctor
            ? pickName({ ar: row.original.doctor.name_ar, en: row.original.doctor.name_en }, language)
            : "—",
      },
      {
        id: "status",
        header: t("board.status"),
        meta: { label: t("board.status") },
        enableSorting: false,
        cell: ({ row }) => (
          <span className="flex flex-wrap gap-1.5">
            <QueueStatusBadge status={row.original.status} />
            {row.original.priority > 0 ? <span className="sr-only">{t("board.emergency")}</span> : null}
          </span>
        ),
      },
      {
        id: "fee",
        header: t("board.fee"),
        meta: { label: t("board.fee") },
        enableSorting: false,
        cell: ({ row }) => <FeeBadge ready={row.original.ready} />,
      },
      {
        id: "since",
        header: t("board.since"),
        meta: { label: t("board.since") },
        accessorKey: "created_at",
        cell: ({ row }) => <DateText value={row.original.created_at} format="time" />,
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps -- n only reads language
    [t, language],
  );

  const waiting = rows.filter((r) => r.status === "waiting").length;
  const serving = rows.filter((r) => r.status === "called" || r.status === "in_progress").length;
  const unpaid = rows.filter((r) => r.status === "waiting" && !r.ready).length;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        icon={<ListOrdered />}
        title={t("queue.title")}
        description={t("queue.description")}
        actions={
          <>
            <Button asChild variant="outline">
              <Link to="/queue/display" search={departmentId ? { department: departmentId } : {}}>
                <MonitorPlay aria-hidden="true" />
                {t("board.displayLink")}
              </Link>
            </Button>
            <Can permission="visits.create">
              <Button
                variant="outline"
                onClick={() => {
                  setCreateOpen(true);
                }}
              >
                <Plus aria-hidden="true" />
                {t("create.open")}
              </Button>
            </Can>
            <Can permission="visits.manage_queue">
              <Button disabled={departmentId === null} loading={callNext.isPending} onClick={() => void onCallNext()}>
                <Megaphone aria-hidden="true" />
                {t("board.callNext")}
              </Button>
            </Can>
          </>
        }
      />

      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="grid gap-1.5 sm:w-72">
          <Label htmlFor="board-department">{t("board.department")}</Label>
          <Select
            value={departmentId ? String(departmentId) : ALL}
            onValueChange={(v) => {
              setDepartmentId(v === ALL ? null : Number(v));
            }}
          >
            <SelectTrigger id="board-department">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>{t("board.allDepartments")}</SelectItem>
              {departments.map((d) => (
                <SelectItem key={d.id} value={String(d.id)}>
                  {pickName({ ar: d.name_ar, en: d.name_en }, language)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <label className="flex items-center gap-2 text-sm text-fg">
          <Switch checked={showFinished} onCheckedChange={setShowFinished} />
          {t("board.showFinished")}
        </label>
      </div>
      {departmentId === null ? <p className="text-sm text-muted">{t("board.pickDepartment")}</p> : null}

      <section aria-label={t("board.summary")} className="grid grid-cols-3 gap-3 md:gap-4">
        <KpiCard label={t("board.kpiWaiting")} value={n(waiting)} icon={<ListOrdered />} />
        <KpiCard label={t("board.kpiServing")} value={n(serving)} icon={<Stethoscope />} tone="info" />
        <KpiCard label={t("board.kpiUnpaid")} value={n(unpaid)} icon={<Megaphone />} tone="warning" />
      </section>

      <DataTable
        caption={
          department
            ? t("board.captionFor", { name: pickName({ ar: department.name_ar, en: department.name_en }, language) })
            : t("board.caption")
        }
        columns={columns}
        data={rows}
        loading={board.isPending}
        getRowId={(r) => String(r.id)}
        rowActions={actionsFor}
        pageSize={50}
        minTableWidth={820}
        renderCard={(r, { actions }) => (
          <div className="card-surface relative flex items-start gap-3 p-4" data-testid="queue-card">
            <span className="flex size-12 shrink-0 items-center justify-center rounded-card bg-primary-soft tabular text-xl font-bold text-primary-strong">
              {n(r.token_no)}
            </span>
            <div className="flex min-w-0 flex-1 flex-col gap-1.5">
              <DataTableOpenButton
                onOpen={() => {
                  void navigate({ to: "/patients/$patientId", params: { patientId: String(r.patient.id) } });
                }}
                label={t("board.action.openFile")}
              >
                <span className="font-semibold break-words text-fg">{patientName(r.patient, language)}</span>
              </DataTableOpenButton>
              <span className="text-xs text-muted">
                {r.doctor
                  ? pickName({ ar: r.doctor.name_ar, en: r.doctor.name_en }, language)
                  : pickName({ ar: r.department.name_ar, en: r.department.name_en }, language)}
              </span>
              <span className="flex flex-wrap gap-1.5">
                <QueueStatusBadge status={r.status} />
                <FeeBadge ready={r.ready} />
              </span>
            </div>
            <div className="relative z-10">{actions}</div>
          </div>
        )}
        emptyState={
          <EmptyState
            icon={<ListOrdered />}
            title={t("board.emptyTitle")}
            description={t("board.emptyDescription")}
            action={
              <Can permission="visits.create">
                <Button
                  onClick={() => {
                    setCreateOpen(true);
                  }}
                >
                  {t("create.open")}
                </Button>
              </Can>
            }
          />
        }
      />

      <CreateVisitDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        defaultDepartmentId={departmentId}
        onCreated={(visit) => {
          toast.success(t("create.done", { number: visit.visit.number }));
          if (visit.queue_entry) setTokenEntry(visit.queue_entry.id);
        }}
      />
      <TokenSlipDialog
        entryId={tokenEntry}
        onOpenChange={(open) => {
          if (!open) setTokenEntry(null);
        }}
      />
      <CancelVisitDialog
        visit={cancelling}
        onOpenChange={(open) => {
          if (!open) setCancelling(null);
        }}
      />
    </div>
  );
}
