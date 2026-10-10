import type { ColumnDef } from "@tanstack/react-table";
import { ArrowRight, ScrollText, X } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { DataTable } from "@/components/DataTable";
import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useCurrentUser } from "@/lib/auth/hooks";
import { hasPermission } from "@/lib/auth/permissions";
import { useLanguage } from "@/lib/i18n-hooks";

import { AdminPage, QueryState } from "../components/AdminPage";
import { AUDIT_PAGE_SIZE, useAuditEvents, useAuditModels, type AuditFilters } from "../ops-api";
import type { AuditAction, AuditEvent, AuditModel } from "../ops-types";

const ALL = "__all__";
const ACTIONS: readonly AuditAction[] = ["insert", "update", "delete"];
const ACTION_VARIANT = { insert: "success", update: "info", delete: "danger" } as const;
const MAX_VALUE = 160;

function isoDay(offsetDays: number): string {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return `${String(d.getFullYear())}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function show(value: unknown): string {
  if (value === null || value === undefined || value === "") return "∅";
  const text = typeof value === "string" ? value : JSON.stringify(value);
  return text.length > MAX_VALUE ? `${text.slice(0, MAX_VALUE)}…` : text;
}

interface UserChip {
  id: number;
  name: string;
}

/**
 * The audit trail (FEATURES 0.4; core.view_audit): every change to a tracked record with who
 * made it, when, the reason and the fields before and after, newest first. Filters: record
 * type, action, days, object id and (from an event) one user.
 */
export function AuditPage() {
  const { t } = useTranslation(["ops", "admin"]);
  const language = useLanguage();
  const me = useCurrentUser();
  const allowed = hasPermission(me, "core.view_audit");
  const models = useAuditModels(allowed);
  const [model, setModel] = useState<string>(ALL);
  const [action, setAction] = useState<string>(ALL);
  const [dateFrom, setDateFrom] = useState(isoDay(-6));
  const [dateTo, setDateTo] = useState(isoDay(0));
  const [objectId, setObjectId] = useState("");
  const [user, setUser] = useState<UserChip | null>(null);
  const [page, setPage] = useState(1);

  const filters: AuditFilters = {
    model: model === ALL ? null : model,
    action: action === ALL ? null : (action as AuditAction),
    dateFrom: dateFrom || null,
    dateTo: dateTo || null,
    objectId: model !== ALL && objectId.trim() ? objectId.trim() : null,
    userId: user?.id ?? null,
    page,
  };
  const events = useAuditEvents(filters, allowed);
  const modelName = useModelName(models.data ?? []);

  const reset = (apply: () => void) => {
    apply();
    setPage(1);
  };

  const columns = useMemo<ColumnDef<AuditEvent>[]>(
    () => [
      {
        id: "event",
        header: t("audit.event"),
        meta: { label: t("audit.event") },
        enableSorting: false,
        cell: ({ row }) => <span>{row.original.id}</span>,
      },
    ],
    [t],
  );

  return (
    <AdminPage section="audit" title={t("admin:sections.audit.title")} description={t("audit.description")}>
      <section
        aria-label={t("audit.filters")}
        className="card-surface grid gap-4 p-4 sm:grid-cols-2 md:p-5 xl:grid-cols-4"
      >
        <div className="grid min-w-0 gap-1.5">
          <Label htmlFor="audit-model">{t("audit.model")}</Label>
          <Select
            value={model}
            onValueChange={(value) => {
              reset(() => {
                setModel(value);
                if (value === ALL) setObjectId("");
              });
            }}
          >
            <SelectTrigger id="audit-model" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>{t("audit.allModels")}</SelectItem>
              {(models.data ?? []).map((m) => (
                <SelectItem key={m.label} value={m.label}>
                  {modelName(m.label)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="grid min-w-0 gap-1.5">
          <Label htmlFor="audit-action">{t("audit.action")}</Label>
          <Select
            value={action}
            onValueChange={(value) => {
              reset(() => {
                setAction(value);
              });
            }}
          >
            <SelectTrigger id="audit-action" className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>{t("audit.allActions")}</SelectItem>
              {ACTIONS.map((a) => (
                <SelectItem key={a} value={a}>
                  {t(`audit.actions.${a}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="grid min-w-0 gap-1.5">
          <Label htmlFor="audit-from">{t("audit.dateFrom")}</Label>
          <Input
            id="audit-from"
            type="date"
            dir="ltr"
            value={dateFrom}
            max={dateTo || undefined}
            onChange={(e) => {
              reset(() => {
                setDateFrom(e.target.value);
              });
            }}
          />
        </div>
        <div className="grid min-w-0 gap-1.5">
          <Label htmlFor="audit-to">{t("audit.dateTo")}</Label>
          <Input
            id="audit-to"
            type="date"
            dir="ltr"
            value={dateTo}
            min={dateFrom || undefined}
            onChange={(e) => {
              reset(() => {
                setDateTo(e.target.value);
              });
            }}
          />
        </div>
        {model !== ALL ? (
          <div className="grid min-w-0 gap-1.5">
            <Label htmlFor="audit-object">{t("audit.objectId")}</Label>
            <Input
              id="audit-object"
              dir="ltr"
              inputMode="numeric"
              maxLength={64}
              value={objectId}
              onChange={(e) => {
                reset(() => {
                  setObjectId(e.target.value);
                });
              }}
            />
          </div>
        ) : null}
        {user ? (
          <div className="flex min-w-0 items-end">
            <Badge variant="outline" className="h-9 max-w-full gap-1.5 px-3 text-sm">
              <span className="truncate">{t("audit.onlyUser", { name: user.name })}</span>
              <button
                type="button"
                className="rounded-full focus-ring"
                aria-label={t("audit.clearUser")}
                onClick={() => {
                  reset(() => {
                    setUser(null);
                  });
                }}
              >
                <X className="size-3.5" aria-hidden="true" />
              </button>
            </Badge>
          </div>
        ) : null}
      </section>

      <QueryState
        loading={events.isPending}
        error={events.isError ? events.error : null}
        onRetry={() => void events.refetch()}
        rows={5}
      >
        <DataTable
          caption={t("audit.caption")}
          mode="cards"
          columns={columns}
          data={events.data?.items ?? []}
          getRowId={(e) => e.id}
          serverPagination={{
            page,
            pageSize: AUDIT_PAGE_SIZE,
            count: events.data?.count ?? 0,
            onPageChange: setPage,
          }}
          renderCard={(event) => (
            <AuditCard
              event={event}
              modelName={modelName(event.model, event.model_name)}
              onUser={(chip) => {
                reset(() => {
                  setUser(chip);
                });
              }}
              language={language}
            />
          )}
          emptyState={<EmptyState size="compact" icon={<ScrollText />} title={t("audit.empty")} />}
        />
      </QueryState>
    </AdminPage>
  );
}

function useModelName(models: AuditModel[]) {
  const { t } = useTranslation("ops");
  const byLabel = useMemo(() => new Map(models.map((m) => [m.label, m.verbose_name])), [models]);
  return (label: string, fallback?: string) =>
    t(`audit.models.${label.replace(".", "_")}`, { defaultValue: byLabel.get(label) ?? fallback ?? label });
}

function AuditCard({
  event,
  modelName,
  onUser,
  language,
}: {
  event: AuditEvent;
  modelName: string;
  onUser: (chip: UserChip) => void;
  language: string;
}) {
  const { t } = useTranslation("ops");
  const userName = event.user
    ? language === "ar"
      ? event.user.name_ar || event.user.name_en
      : event.user.name_en || event.user.name_ar
    : null;
  const action = event.action in ACTION_VARIANT ? (event.action as AuditAction) : null;
  return (
    <article className="card-surface flex flex-col gap-2 p-4" data-testid="audit-event">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
          <Badge variant={action ? ACTION_VARIANT[action] : "outline"}>
            {action ? t(`audit.actions.${action}`) : event.action}
          </Badge>
          <span className="font-medium break-words text-fg">{modelName}</span>
          {event.object_id ? (
            <bdi className="tabular text-sm text-muted">{t("audit.objectRef", { id: event.object_id })}</bdi>
          ) : null}
        </span>
        <DateText value={event.created_at} format="datetime" className="text-sm text-muted" />
      </header>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
        {event.user && userName ? (
          <Button
            variant="link"
            size="sm"
            className="h-auto p-0"
            onClick={() => {
              onUser({ id: event.user?.id ?? 0, name: userName });
            }}
          >
            {userName}
          </Button>
        ) : (
          <span className="text-muted">{t("audit.system")}</span>
        )}
        {event.reason ? <span className="break-words text-muted">{event.reason}</span> : null}
        {event.method && event.url ? (
          <bdi className="text-xs break-all text-muted">
            {event.method} {event.url}
          </bdi>
        ) : null}
      </div>
      {event.changes.length > 0 ? (
        <dl className="grid gap-1 border-t border-border pt-2 text-xs">
          {event.changes.map((change) => (
            <div key={change.field} className="grid min-w-0 gap-x-3 sm:grid-cols-[minmax(8rem,auto)_1fr]">
              <dt>
                <bdi className="font-medium text-fg">{change.field}</bdi>
              </dt>
              <dd className="min-w-0 break-words text-muted">
                {event.action === "update" ? (
                  <>
                    <bdi className="line-through decoration-danger/60">{show(change.before)}</bdi>
                    <ArrowRight className="mx-1 inline size-3 rtl:-scale-x-100" aria-hidden="true" />
                    <span className="sr-only">{t("audit.becomes")}</span>
                    <bdi className="text-fg">{show(change.after)}</bdi>
                  </>
                ) : (
                  <bdi>{show(event.action === "delete" ? change.before : change.after)}</bdi>
                )}
              </dd>
            </div>
          ))}
        </dl>
      ) : null}
    </article>
  );
}
