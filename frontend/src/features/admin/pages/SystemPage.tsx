import type { ColumnDef } from "@tanstack/react-table";
import { Archive, Database, DatabaseBackup, HardDrive, History, RefreshCw, ShieldCheck, Tag } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { AlertCard } from "@/components/AlertCard";
import { Can } from "@/components/Can";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { DataTable } from "@/components/DataTable";
import { DateText } from "@/components/DateText";
import { KpiCard } from "@/components/KpiCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useLanguage } from "@/lib/i18n-hooks";
import { cn } from "@/lib/utils";

import { AdminPage, QueryState } from "../components/AdminPage";
import { useRequestBackup, useSystemStatus, useUpdateHistory } from "../ops-api";
import { formatBytes } from "../ops-format";
import type { BackupRequest, OpsRun, SystemStatus, UpdateLog, UpdateRun } from "../ops-types";

type BadgeVariant = "success" | "warning" | "danger" | "outline" | "info";

const RUN_VARIANT: Record<string, BadgeVariant> = {
  ok: "success",
  succeeded: "success",
  partial: "warning",
  failed: "danger",
  rolled_back: "warning",
  running: "info",
  pending: "outline",
};

function runVariant(status: string): BadgeVariant {
  return RUN_VARIANT[status] ?? "outline";
}

/**
 * System status (FEATURES 0.8, 13.8, 13.10, 14.1): database, disk space, version and
 * migrations, the last backups and restore tests with warnings, manual backup requests and
 * the update history. Everything is read from the server; "Back up now" only records a
 * request that the backup service picks up within a minute or two.
 */
export function SystemPage() {
  const { t } = useTranslation(["ops", "admin"]);
  const status = useSystemStatus();
  const request = useRequestBackup();
  const [asking, setAsking] = useState(false);
  const [note, setNote] = useState("");
  const open = status.data?.backup_requests.find((r) => r.status === "pending" || r.status === "running");

  return (
    <AdminPage
      section="system"
      title={t("admin:sections.system.title")}
      description={t("system.description")}
      actions={
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => void status.refetch()} loading={status.isRefetching}>
            <RefreshCw aria-hidden="true" />
            {t("system.refresh")}
          </Button>
          <Can permission="ops.trigger_backup">
            <Button
              disabled={Boolean(open)}
              onClick={() => {
                setNote("");
                setAsking(true);
              }}
            >
              <DatabaseBackup aria-hidden="true" />
              {t("system.backupNow")}
            </Button>
          </Can>
        </div>
      }
    >
      <QueryState
        loading={status.isPending}
        error={status.isError ? status.error : null}
        onRetry={() => void status.refetch()}
        rows={6}
      >
        {status.data ? <StatusBody status={status.data} openRequest={open} /> : null}
      </QueryState>
      <UpdatesSection />
      <ConfirmDialog
        open={asking}
        onOpenChange={setAsking}
        title={t("system.backupNowTitle")}
        description={t("system.backupNowDescription")}
        confirmLabel={t("system.backupNow")}
        onConfirm={async () => {
          await request.mutateAsync(note);
          toast.success(t("system.backupRequested"));
        }}
      >
        <div className="grid gap-1.5">
          <Label htmlFor="backup-note">{t("system.backupNote")}</Label>
          <Input
            id="backup-note"
            maxLength={200}
            value={note}
            onChange={(e) => {
              setNote(e.target.value);
            }}
          />
        </div>
      </ConfirmDialog>
    </AdminPage>
  );
}

function StatusBody({ status, openRequest }: { status: SystemStatus; openRequest: BackupRequest | undefined }) {
  const { t } = useTranslation("ops");
  const language = useLanguage();
  const lastBackup = status.last_backup;
  const lastRestore = status.last_restore_test;
  return (
    <div className="flex flex-col gap-5">
      {status.warnings.length > 0 ? (
        <ul className="grid gap-2" aria-label={t("system.warningsTitle")}>
          {status.warnings.map((code) => (
            <li key={code}>
              <AlertCard
                variant={code === "BACKUP_STALE" || code === "MIGRATIONS_PENDING" ? "warning" : "danger"}
                title={t(`system.warnings.${code}.title`)}
              >
                {t(`system.warnings.${code}.description`)}
              </AlertCard>
            </li>
          ))}
        </ul>
      ) : (
        <AlertCard variant="success" title={t("system.allGood")}>
          {t("system.allGoodDescription")}
        </AlertCard>
      )}

      {openRequest ? (
        <AlertCard variant="info" live title={t(`system.request.${openRequest.status}`)}>
          {t("system.requestHint")}
        </AlertCard>
      ) : null}

      <section aria-label={t("system.summary")} className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard label={t("system.version")} value={<bdi className="tabular">{status.version}</bdi>} icon={<Tag />} />
        <KpiCard
          label={t("system.database")}
          value={status.database.ok ? t("system.dbOk") : t("system.dbDown")}
          tone={status.database.ok ? "success" : "danger"}
          icon={<Database />}
          hint={
            status.database.size_bytes != null
              ? t("system.dbHint", {
                  version: status.database.server_version,
                  size: formatBytes(status.database.size_bytes, language),
                })
              : undefined
          }
        />
        <KpiCard
          label={t("system.lastBackup")}
          value={
            lastBackup?.finished_at ? <DateText value={lastBackup.finished_at} format="relative" /> : t("system.never")
          }
          tone={status.warnings.includes("BACKUP_STALE") ? "warning" : "success"}
          icon={<Archive />}
          hint={lastBackup ? <RunHint run={lastBackup} /> : undefined}
        />
        <KpiCard
          label={t("system.lastRestoreTest")}
          value={
            lastRestore?.finished_at ? (
              <DateText value={lastRestore.finished_at} format="relative" />
            ) : (
              t("system.never")
            )
          }
          tone={
            status.warnings.includes("RESTORE_TEST_FAILED") || status.warnings.includes("RESTORE_TEST_STALE")
              ? "warning"
              : "success"
          }
          icon={<ShieldCheck />}
          hint={
            lastRestore ? t(`system.runStatus.${lastRestore.status}`, { defaultValue: lastRestore.status }) : undefined
          }
        />
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="card-surface flex flex-col gap-3 p-4 md:p-5" aria-labelledby="sys-disks">
          <h2 id="sys-disks" className="flex items-center gap-2 text-base font-semibold text-fg">
            <HardDrive className="size-4 text-muted" aria-hidden="true" />
            {t("system.disks")}
          </h2>
          {status.disks.length === 0 ? (
            <p className="text-sm text-muted">{t("system.noDisks")}</p>
          ) : (
            <ul className="grid gap-3">
              {status.disks.map((disk) => {
                const used = Math.max(0, Math.min(100, 100 - disk.free_percent));
                return (
                  <li key={disk.label} className="grid gap-1.5">
                    <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                      <span className="font-medium text-fg">{t(`system.disk.${disk.label}`)}</span>
                      <span className="tabular text-muted">
                        {t("system.diskFree", {
                          free: formatBytes(disk.free_bytes, language),
                          total: formatBytes(disk.total_bytes, language),
                        })}
                      </span>
                    </div>
                    <div
                      className="h-2 overflow-hidden rounded-full bg-subtle"
                      role="meter"
                      aria-label={t(`system.disk.${disk.label}`)}
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={Math.round(used)}
                    >
                      <div
                        className={cn("h-full rounded-full", disk.free_percent < 10 ? "bg-danger" : "bg-primary")}
                        style={{ width: `${String(used)}%` }}
                      />
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        <section className="card-surface flex flex-col gap-3 p-4 md:p-5" aria-labelledby="sys-migrations">
          <h2 id="sys-migrations" className="flex items-center gap-2 text-base font-semibold text-fg">
            <Database className="size-4 text-muted" aria-hidden="true" />
            {t("system.migrations")}
          </h2>
          <p className="text-sm text-fg">
            {status.migrations.pending === 0
              ? t("system.migrationsOk", { count: status.migrations.applied })
              : t("system.migrationsPending", { count: status.migrations.pending })}
          </p>
          {status.migrations.pending_names.length > 0 ? (
            <ul className="grid gap-1 text-xs text-muted">
              {status.migrations.pending_names.map((name) => (
                <li key={name}>
                  <bdi className="tabular">{name}</bdi>
                </li>
              ))}
            </ul>
          ) : null}
          <p className="text-sm text-muted">{t("system.pendingCloud", { count: status.pending_cloud_uploads })}</p>
        </section>
      </div>

      <RunsSection title={t("system.backups")} runs={status.backups} id="sys-backups" kind="backup" />
      <RunsSection title={t("system.restoreTests")} runs={status.restore_tests} id="sys-restores" kind="restore" />
      <RequestsSection requests={status.backup_requests} />
    </div>
  );
}

function RunHint({ run }: { run: OpsRun }) {
  const { t } = useTranslation("ops");
  const language = useLanguage();
  const parts: string[] = [t(`system.runStatus.${run.status}`, { defaultValue: run.status })];
  if (run.size_bytes != null) parts.push(formatBytes(run.size_bytes, language));
  return <span>{parts.join(" · ")}</span>;
}

function RunsSection({
  title,
  runs,
  id,
  kind,
}: {
  title: string;
  runs: OpsRun[];
  id: string;
  kind: "backup" | "restore";
}) {
  const { t } = useTranslation("ops");
  const language = useLanguage();
  const columns = useMemo<ColumnDef<OpsRun>[]>(
    () => [
      {
        id: "finished",
        header: t("system.when"),
        meta: { label: t("system.when") },
        enableSorting: false,
        cell: ({ row }) => {
          const when = row.original.finished_at ?? row.original.started_at;
          return when ? <DateText value={when} format="datetime" /> : null;
        },
      },
      {
        id: "status",
        header: t("system.status"),
        meta: { label: t("system.status") },
        enableSorting: false,
        cell: ({ row }) => (
          <Badge variant={runVariant(row.original.status)}>
            {t(`system.runStatus.${row.original.status}`, { defaultValue: row.original.status })}
          </Badge>
        ),
      },
      {
        id: "detail",
        header: t("system.detail"),
        meta: { label: t("system.detail") },
        enableSorting: false,
        cell: ({ row }) => <RunDetail run={row.original} kind={kind} />,
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps -- formatting reads language
    [t, language, kind],
  );
  return (
    <section className="flex flex-col gap-3" aria-labelledby={id}>
      <h2 id={id} className="flex items-center gap-2 text-base font-semibold text-fg">
        <History className="size-4 text-muted" aria-hidden="true" />
        {title}
      </h2>
      <DataTable
        caption={title}
        columns={columns}
        data={runs}
        getRowId={(r, i) => `${r.source}-${String(i)}`}
        pageSize={10}
        renderCard={(r) => (
          <div className="card-surface flex flex-col gap-1.5 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <RunWhen run={r} />
              <Badge variant={runVariant(r.status)}>
                {t(`system.runStatus.${r.status}`, { defaultValue: r.status })}
              </Badge>
            </div>
            <RunDetail run={r} kind={kind} />
          </div>
        )}
        emptyState={<p className="p-4 text-sm text-muted">{t("system.noRuns")}</p>}
      />
    </section>
  );
}

function RunWhen({ run }: { run: OpsRun }) {
  const when = run.finished_at ?? run.started_at;
  return when ? <DateText value={when} format="datetime" className="text-sm" /> : <span />;
}

function RunDetail({ run, kind }: { run: OpsRun; kind: "backup" | "restore" }) {
  const { t } = useTranslation("ops");
  const language = useLanguage();
  const facts: ReactNode[] = [];
  if (run.label) facts.push(<bdi key="l">{run.label}</bdi>);
  if (run.file)
    facts.push(
      <bdi key="f" className="break-all">
        {run.file}
      </bdi>,
    );
  if (kind === "backup" && run.size_bytes != null)
    facts.push(<span key="s">{formatBytes(run.size_bytes, language)}</span>);
  return (
    <span className="flex min-w-0 flex-col gap-0.5 text-sm">
      {facts.length > 0 ? (
        <span className="text-muted">
          {facts.map((fact, i) => (
            <span key={i}>
              {i > 0 ? " · " : ""}
              {fact}
            </span>
          ))}
        </span>
      ) : null}
      {run.error ? <span className="break-words text-danger">{run.error}</span> : null}
      {run.source === "db" ? <span className="text-xs text-muted">{t("system.fromDatabase")}</span> : null}
    </span>
  );
}

function RequestsSection({ requests }: { requests: BackupRequest[] }) {
  const { t } = useTranslation("ops");
  const language = useLanguage();
  if (requests.length === 0) return null;
  return (
    <section className="flex flex-col gap-3" aria-labelledby="sys-requests">
      <h2 id="sys-requests" className="text-base font-semibold text-fg">
        {t("system.requests")}
      </h2>
      <ul className="grid gap-2">
        {requests.map((r) => (
          <li key={r.id} className="card-surface flex flex-col gap-1 px-4 py-3 text-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="flex flex-wrap items-center gap-x-2 text-fg">
                <DateText value={r.requested_at} format="datetime" />
                <span className="text-muted">
                  {language === "ar"
                    ? r.requested_by.name_ar || r.requested_by.name_en
                    : r.requested_by.name_en || r.requested_by.name_ar}
                </span>
              </span>
              <Badge variant={runVariant(r.status)} data-status={r.status}>
                {t(`system.request.${r.status}`)}
              </Badge>
            </div>
            {r.note ? <span className="break-words text-muted">{r.note}</span> : null}
            {r.dump_file ? <bdi className="text-xs break-all text-muted">{r.dump_file}</bdi> : null}
            {r.message ? <span className="text-xs break-words text-danger">{r.message}</span> : null}
          </li>
        ))}
      </ul>
    </section>
  );
}

function UpdatesSection() {
  const { t } = useTranslation("ops");
  const [page, setPage] = useState(1);
  const updates = useUpdateHistory(page);
  return (
    <section className="flex flex-col gap-3" aria-labelledby="sys-updates">
      <h2 id="sys-updates" className="text-base font-semibold text-fg">
        {t("system.updates")}
      </h2>
      <QueryState
        loading={updates.isPending}
        error={updates.isError ? updates.error : null}
        onRetry={() => void updates.refetch()}
        rows={2}
      >
        {updates.data ? (
          <div className="flex flex-col gap-3">
            <p className="text-sm text-fg">
              {t("system.currentVersion")} <bdi className="tabular font-semibold">{updates.data.current_version}</bdi>
            </p>
            {updates.data.items.length === 0 && updates.data.log.length === 0 ? (
              <p className="text-sm text-muted">{t("system.noUpdates")}</p>
            ) : null}
            {updates.data.items.length > 0 ? (
              <ul className="grid gap-2">
                {updates.data.items.map((u) => (
                  <UpdateRunItem key={u.id} run={u} />
                ))}
              </ul>
            ) : null}
            {updates.data.count > updates.data.page_size ? (
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={page <= 1}
                  onClick={() => {
                    setPage((p) => Math.max(1, p - 1));
                  }}
                >
                  {t("system.newer")}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={page * updates.data.page_size >= updates.data.count}
                  onClick={() => {
                    setPage((p) => p + 1);
                  }}
                >
                  {t("system.older")}
                </Button>
              </div>
            ) : null}
            {updates.data.log.length > 0 ? (
              <div className="flex flex-col gap-2">
                <h3 className="text-sm font-semibold text-fg">{t("system.updateLog")}</h3>
                <ul className="grid gap-2">
                  {updates.data.log.map((entry, i) => (
                    <UpdateLogItem key={i} entry={entry} />
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        ) : null}
      </QueryState>
    </section>
  );
}

function UpdateRunItem({ run }: { run: UpdateRun }) {
  const { t } = useTranslation("ops");
  return (
    <li className="card-surface flex flex-col gap-2 px-4 py-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex flex-wrap items-center gap-x-2">
          <bdi className="tabular font-semibold text-fg">{run.version}</bdi>
          {run.previous_version ? (
            <span className="text-muted">{t("system.fromVersion", { version: run.previous_version })}</span>
          ) : null}
          <DateText value={run.started_at} format="datetime" className="text-muted" />
        </span>
        <Badge variant={runVariant(run.result)}>{t(`system.updateResult.${run.result}`)}</Badge>
      </div>
      {run.release_notes ? (
        <details>
          <summary className="cursor-pointer text-primary-strong">{t("system.releaseNotes")}</summary>
          <p className="mt-2 break-words whitespace-pre-line text-fg">{run.release_notes}</p>
        </details>
      ) : null}
    </li>
  );
}

function UpdateLogItem({ entry }: { entry: UpdateLog }) {
  const { t } = useTranslation("ops");
  return (
    <li className="card-surface flex flex-col gap-1 px-4 py-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex flex-wrap items-center gap-x-2">
          <span className="text-fg">
            {t("system.updateFromTo", { from: entry.from_tag || "—", to: entry.to_tag || "—" })}
          </span>
          {entry.finished_at ? <DateText value={entry.finished_at} format="datetime" className="text-muted" /> : null}
        </span>
        <Badge variant={runVariant(entry.status)}>
          {t(`system.runStatus.${entry.status}`, { defaultValue: entry.status })}
        </Badge>
      </div>
      {entry.detail ? <span className="break-words text-muted">{entry.detail}</span> : null}
    </li>
  );
}
