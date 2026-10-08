import { zodResolver } from "@hookform/resolvers/zod";
import { ChevronDown, Lock, RotateCcw, Save } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { z } from "zod";

import { TextareaField } from "@/components/form";
import { SearchInput } from "@/components/SearchInput";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Switch } from "@/components/ui/switch";
import { isKnownRole } from "@/lib/auth/permissions";
import { useElementWidth } from "@/lib/hooks/use-element-width";
import { useBreakpoint } from "@/lib/hooks/use-media-query";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";
import { cn } from "@/lib/utils";
import { translateKey, vmsg } from "@/lib/validation";

import { usePermissionMatrix, useUpdateMatrix } from "../api";
import { AdminPage, QueryState } from "../components/AdminPage";
import { FormDialog } from "../components/FormDialog";
import type { MatrixChangeIn, PermissionRowOut, RoleOut } from "../types";

/** Container width from which the grid (one column per role) replaces the per-role lists. */
const GRID_MIN_WIDTH = 640;

type Pending = ReadonlyMap<string, boolean>;
const cellKey = (role: string, code: string) => `${role}|${code}`;

const reasonSchema = z.object({ reason: z.string().trim().min(1, vmsg("validation.required")).max(500) });
type ReasonValues = z.infer<typeof reasonSchema>;

interface Group {
  app: string;
  rows: PermissionRowOut[];
}

function groupByApp(rows: readonly PermissionRowOut[]): Group[] {
  const groups = new Map<string, PermissionRowOut[]>();
  for (const row of rows) {
    const list = groups.get(row.app) ?? [];
    list.push(row);
    groups.set(row.app, list);
  }
  return [...groups.entries()].map(([app, list]) => ({ app, rows: list }));
}

export function RolesPage() {
  const { t } = useTranslation("admin");
  const matrix = usePermissionMatrix();
  const save = useUpdateMatrix();
  const [pending, setPending] = useState<Pending>(new Map());
  const [query, setQuery] = useState("");
  const [confirming, setConfirming] = useState(false);
  const language = useLanguage();
  const container = useRef<HTMLDivElement>(null);
  const width = useElementWidth(container);
  const isMd = useBreakpoint("md");
  const wide = width !== null ? width >= GRID_MIN_WIDTH : isMd;

  const data = matrix.data;
  const filtered = useMemo(() => {
    if (!data) return [];
    const q = query.trim().toLowerCase();
    if (!q) return data.permissions;
    return data.permissions.filter(
      (p) => p.code.includes(q) || p.label_ar.toLowerCase().includes(q) || p.label_en.toLowerCase().includes(q),
    );
  }, [data, query]);
  const groups = useMemo(() => groupByApp(filtered), [filtered]);

  const granted = (row: PermissionRowOut, role: string): boolean =>
    pending.get(cellKey(role, row.code)) ?? row.granted_roles.includes(role);

  const toggle = (row: PermissionRowOut, role: string, value: boolean) => {
    setPending((current) => {
      const next = new Map(current);
      const key = cellKey(role, row.code);
      if (value === row.granted_roles.includes(role)) next.delete(key);
      else next.set(key, value);
      return next;
    });
  };

  const changes: MatrixChangeIn[] = [...pending.entries()].map(([key, allowed]) => {
    const [role = "", code = ""] = key.split("|");
    return { role: role as MatrixChangeIn["role"], code, allowed };
  });

  const form = useForm<ReasonValues>({ resolver: zodResolver(reasonSchema), defaultValues: { reason: "" } });

  const cellProps = {
    granted,
    toggle,
    pending,
    label: (row: PermissionRowOut) => pickName({ ar: row.label_ar, en: row.label_en }, language),
  };

  return (
    <AdminPage section="roles" title={t("sections.roles.title")} description={t("sections.roles.description")}>
      <div ref={container} className="min-w-0">
        <QueryState loading={matrix.isPending} error={matrix.error} onRetry={() => void matrix.refetch()} rows={8}>
          {data ? (
            <div className="flex min-w-0 flex-col gap-4">
              <SearchInput
                label={t("roles.search")}
                placeholder={t("roles.search")}
                value={query}
                onValueChange={setQuery}
                className="sm:max-w-sm"
              />
              {wide ? (
                <MatrixGrid roles={data.roles} groups={groups} {...cellProps} />
              ) : (
                <RoleLists roles={data.roles} groups={groups} {...cellProps} />
              )}
            </div>
          ) : null}
        </QueryState>
      </div>

      {pending.size > 0 ? (
        <div
          role="region"
          aria-label={t("roles.pendingRegion")}
          className="sticky bottom-20 z-20 flex flex-col gap-3 rounded-card border border-warning-border bg-warning-bg p-3 text-warning-fg shadow-overlay sm:flex-row sm:items-center sm:justify-between lg:bottom-4"
        >
          <span className="text-sm font-medium">{t("roles.pending", { count: pending.size })}</span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              onClick={() => {
                setPending(new Map());
              }}
            >
              <RotateCcw />
              {t("roles.discard")}
            </Button>
            <Button
              onClick={() => {
                setConfirming(true);
              }}
            >
              <Save />
              {t("roles.save")}
            </Button>
          </div>
        </div>
      ) : null}

      <FormDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={t("roles.confirmTitle")}
        description={t("roles.confirmHint", { count: pending.size })}
        form={form}
        error={save.error}
        onSubmit={async (values) => {
          await save.mutateAsync({ changes, reason: values.reason });
          toast.success(t("roles.saved"));
          setConfirming(false);
          setPending(new Map());
          form.reset();
        }}
      >
        <TextareaField control={form.control} name="reason" label={t("common.reason")} rows={3} required />
      </FormDialog>
    </AdminPage>
  );
}

interface CellProps {
  roles: readonly RoleOut[];
  groups: readonly Group[];
  granted: (row: PermissionRowOut, role: string) => boolean;
  toggle: (row: PermissionRowOut, role: string, value: boolean) => void;
  pending: Pending;
  label: (row: PermissionRowOut) => string;
}

function useRoleName() {
  const { t } = useTranslation("common");
  const language = useLanguage();
  return (role: RoleOut) =>
    isKnownRole(role.code) ? t(`roles.${role.code}`) : pickName({ ar: role.name_ar, en: role.name_en }, language);
}

function useAppName() {
  const { t } = useTranslation();
  return (app: string) => translateKey(t, `admin:roles.apps.${app}`, { defaultValue: app });
}

function MatrixGrid({ roles, groups, granted, toggle, pending, label }: CellProps) {
  const { t } = useTranslation("admin");
  const roleName = useRoleName();
  const appName = useAppName();
  return (
    <div
      className="card-surface max-w-full scrollbar-thin overflow-x-auto"
      tabIndex={0}
      role="region"
      aria-label={t("roles.matrix")}
    >
      <table className="w-full border-separate border-spacing-0 text-sm">
        <caption className="sr-only">{t("roles.matrix")}</caption>
        <thead>
          <tr>
            <th
              scope="col"
              className="sticky start-0 z-10 min-w-56 border-b border-border bg-surface px-3 py-2 text-start font-semibold text-fg"
            >
              {t("roles.permission")}
            </th>
            {roles.map((role) => (
              <th key={role.code} scope="col" className="border-b border-border px-1 py-2 align-bottom">
                <span className="mx-auto block w-16 text-center text-xs leading-tight font-medium text-fg-muted">
                  {roleName(role)}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        {groups.map((group) => (
          <tbody key={group.app}>
            <tr>
              <th
                scope="colgroup"
                colSpan={roles.length + 1}
                className="sticky start-0 bg-subtle px-3 py-1.5 text-start text-xs font-semibold tracking-wide text-muted uppercase"
              >
                {appName(group.app)}
              </th>
            </tr>
            {group.rows.map((row) => (
              <tr key={row.code} className="hover:bg-accent/40">
                <th
                  scope="row"
                  className="sticky start-0 z-[1] border-b border-border bg-surface px-3 py-2 text-start font-normal"
                >
                  <span className="block text-fg">{label(row)}</span>
                  <bdi dir="ltr" className="font-mono text-[11px] text-muted">
                    {row.code}
                  </bdi>
                </th>
                {roles.map((role) => {
                  const isProtected = row.protected_roles.includes(role.code);
                  const changed = pending.has(cellKey(role.code, row.code));
                  return (
                    <td
                      key={role.code}
                      className={cn("border-b border-border text-center", changed && "bg-warning-bg")}
                    >
                      <span className="inline-flex size-11 items-center justify-center md:size-9">
                        <Checkbox
                          checked={granted(row, role.code)}
                          disabled={isProtected}
                          aria-label={t("roles.cellLabel", { role: roleName(role), permission: label(row) })}
                          data-testid={`perm-${role.code}-${row.code}`}
                          onCheckedChange={(v) => {
                            toggle(row, role.code, v === true);
                          }}
                        />
                      </span>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        ))}
      </table>
    </div>
  );
}

function RoleLists({ roles, groups, granted, toggle, pending, label }: CellProps) {
  const { t } = useTranslation("admin");
  const roleName = useRoleName();
  const appName = useAppName();
  return (
    <div className="flex flex-col gap-2">
      {roles.map((role) => {
        const count = groups.reduce((n, g) => n + g.rows.filter((r) => granted(r, role.code)).length, 0);
        return (
          <details key={role.code} className="group card-surface overflow-hidden">
            <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 focus-ring-inset">
              <span className="min-w-0">
                <span className="block truncate font-semibold text-fg">{roleName(role)}</span>
                <span className="text-xs text-muted">{t("roles.grantedCount", { count })}</span>
              </span>
              <ChevronDown
                className="size-4 shrink-0 text-muted transition-transform group-open:rotate-180"
                aria-hidden="true"
              />
            </summary>
            <div className="flex flex-col gap-3 border-t border-border px-4 py-3">
              {groups.map((group) => (
                <section key={group.app} aria-label={appName(group.app)}>
                  <h3 className="mb-1 text-xs font-semibold tracking-wide text-muted uppercase">
                    {appName(group.app)}
                  </h3>
                  <ul className="flex flex-col">
                    {group.rows.map((row) => {
                      const id = `m-${role.code}-${row.code}`;
                      const isProtected = row.protected_roles.includes(role.code);
                      const changed = pending.has(cellKey(role.code, row.code));
                      return (
                        <li
                          key={row.code}
                          className={cn(
                            "flex items-center justify-between gap-3 rounded-control py-1.5",
                            changed && "bg-warning-bg px-2",
                          )}
                        >
                          <label htmlFor={id} className="min-w-0 text-sm text-fg">
                            {label(row)}
                            {isProtected ? <Lock className="ms-1 inline size-3 text-muted" aria-hidden="true" /> : null}
                          </label>
                          <Switch
                            id={id}
                            checked={granted(row, role.code)}
                            disabled={isProtected}
                            data-testid={`perm-${role.code}-${row.code}`}
                            onCheckedChange={(v) => {
                              toggle(row, role.code, v);
                            }}
                          />
                        </li>
                      );
                    })}
                  </ul>
                </section>
              ))}
            </div>
          </details>
        );
      })}
      <Badge variant="neutral" className="self-start">
        {t("roles.protectedHint")}
      </Badge>
    </div>
  );
}
