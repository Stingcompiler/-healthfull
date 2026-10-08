import { zodResolver } from "@hookform/resolvers/zod";
import { ShieldCheck } from "lucide-react";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { AlertCard } from "@/components/AlertCard";
import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { Form, SelectField, TextareaField, TextField } from "@/components/form";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";
import { vmsg } from "@/lib/validation";

import {
  PAGE_SIZE,
  useAuthorizations,
  useAuthorize,
  usePerformFirstVisit,
  useReasons,
  useRevokeAuthorization,
} from "../api";
import { CashierNav } from "../components/CashierNav";
import { LookupPanel } from "../components/LookupPanel";
import { NoteDialog } from "../components/NoteDialog";
import { Pager } from "../components/Pager";
import { PatientHeader } from "../components/PatientHeader";
import { useNames } from "../lib/use-names";
import type { Authorization, PerformFirstVisit } from "../types";

const KINDS = ["emergency", "insurance_approval", "credit_account", "other"] as const;

const schema = z
  .object({
    kind: z.enum(KINDS),
    reason: z.string().min(1, vmsg("validation.selectOption")),
    note: z.string().trim().max(1000),
    reference: z.string().trim().max(100),
  })
  .superRefine((v, ctx) => {
    if (v.kind === "insurance_approval" && !v.reference) {
      ctx.addIssue({ code: "custom", path: ["reference"], message: vmsg("validation.required") });
    }
  });

type Values = z.infer<typeof schema>;

/**
 * Perform-first authorization (FEATURES 4.4, invariant 1): a supervisor documents who allowed
 * which unpaid lines to be performed before payment, and why. No prices on this screen.
 */
export function PerformFirstPage() {
  const { t } = useTranslation("cashier");
  const [query, setQuery] = useState("");
  const [visitId, setVisitId] = useState<number | undefined>(undefined);
  const visit = usePerformFirstVisit(visitId);

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader title={t("performFirst.title")} description={t("performFirst.description")} icon={<ShieldCheck />} />
      <CashierNav />
      <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
        <LookupPanel query={query} onQueryChange={setQuery} selectedVisitId={visitId} onSelectVisit={setVisitId} />
        <div className="flex min-w-0 flex-col gap-4">
          {visitId === undefined ? (
            <EmptyState
              icon={<ShieldCheck />}
              title={t("performFirst.pickTitle")}
              description={t("performFirst.pickDescription")}
            />
          ) : visit.isPending ? (
            <Skeleton className="h-48 w-full rounded-card" />
          ) : visit.isError ? null : (
            <AuthorizeForm key={visit.data.visit.id} data={visit.data} />
          )}
        </div>
      </div>
      <AuthorizationList />
    </div>
  );
}

function AuthorizeForm({ data }: { data: PerformFirstVisit }) {
  const { t } = useTranslation(["cashier", "common", "errors"]);
  const translateError = useTranslateError();
  const names = useNames();
  const reasons = useReasons("perform_first");
  const authorize = useAuthorize();
  const [selected, setSelected] = useState<ReadonlySet<number>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<Authorization | null>(null);
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { kind: "emergency", reason: "", note: "", reference: "" },
  });
  const kind = useWatch({ control: form.control, name: "kind" });
  const authorizable = data.lines.filter((l) => l.authorizable);

  const submit = form.handleSubmit(async (v) => {
    setError(null);
    if (selected.size === 0) {
      setError(t("performFirst.chooseLines"));
      return;
    }
    try {
      const auth = await authorize.mutateAsync({
        line_ids: [...selected],
        kind: v.kind,
        reason: v.reason,
        note: v.note,
        approval_reference: v.reference,
      });
      setDone(auth);
      setSelected(new Set());
      form.reset({ kind: "emergency", reason: "", note: "", reference: "" });
    } catch (e) {
      setError(translateError(e));
    }
  });

  return (
    <section className="card-surface flex min-w-0 flex-col gap-4 p-4 md:p-5" data-testid="perform-first-form">
      <PatientHeader
        patient={data.patient}
        visitNumber={data.visit.number}
        department={data.visit.department}
        payer={data.visit.payer}
      />
      {done ? (
        <AlertCard
          variant="success"
          title={t("performFirst.doneTitle")}
          live
          onDismiss={() => {
            setDone(null);
          }}
        >
          {t("performFirst.doneBody", { count: done.lines.length })}
        </AlertCard>
      ) : null}
      {data.lines.length === 0 ? (
        <p className="text-sm text-muted">{t("performFirst.noLines")}</p>
      ) : (
        <ul className="flex flex-col divide-y divide-border">
          {data.lines.map((l) => {
            const id = `pf-line-${String(l.id)}`;
            return (
              <li key={l.id} className="flex flex-wrap items-center gap-3 py-2.5">
                <Checkbox
                  id={id}
                  disabled={!l.authorizable}
                  checked={selected.has(l.id)}
                  onCheckedChange={(value) => {
                    setSelected((prev) => {
                      const next = new Set(prev);
                      if (value === true) next.add(l.id);
                      else next.delete(l.id);
                      return next;
                    });
                  }}
                />
                <label htmlFor={id} className="flex min-w-0 flex-1 flex-col gap-1">
                  <span className="font-medium break-words">{names.name(l.service)}</span>
                  <span className="flex flex-wrap items-center gap-1.5 text-xs text-muted">
                    <span className="tabular">{t("billing.qty", { count: l.quantity })}</span>
                    <StatusBadge status={l.state} size="sm" />
                    {l.authorized ? <Badge variant="soft">{t("billing.authorized")}</Badge> : null}
                  </span>
                </label>
              </li>
            );
          })}
        </ul>
      )}
      {authorizable.length > 0 ? (
        <Form {...form}>
          <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <SelectField
                control={form.control}
                name="kind"
                label={t("performFirst.kind")}
                options={KINDS.map((k) => ({ value: k, label: t(`performFirst.kinds.${k}`) }))}
                required
              />
              <SelectField
                control={form.control}
                name="reason"
                label={t("common:reason.code")}
                placeholder={t("common:reason.codePlaceholder")}
                options={(reasons.data ?? []).map((r) => ({ value: r.code, label: names.label(r) }))}
                required
              />
              {kind === "insurance_approval" ? (
                <TextField
                  control={form.control}
                  name="reference"
                  label={t("performFirst.reference")}
                  dir="ltr"
                  required
                />
              ) : null}
            </div>
            <TextareaField control={form.control} name="note" label={t("common:reason.note")} rows={2} />
            {error ? (
              <AlertCard variant="danger" title={t("errors:title")} live>
                {error}
              </AlertCard>
            ) : null}
            <div className="flex justify-end">
              <Button type="submit" loading={form.formState.isSubmitting} data-testid="authorize">
                {t("performFirst.submit", { count: selected.size })}
              </Button>
            </div>
          </form>
        </Form>
      ) : null}
    </section>
  );
}

function AuthorizationList() {
  const { t } = useTranslation(["cashier", "common"]);
  const names = useNames();
  const [page, setPage] = useState(1);
  const list = useAuthorizations(true, page);
  const revoke = useRevokeAuthorization();
  const [revoking, setRevoking] = useState<Authorization | null>(null);
  const items = list.data?.items ?? [];

  return (
    <section className="card-surface flex min-w-0 flex-col gap-3 p-4 md:p-5" aria-labelledby="auth-list-title">
      <h2 id="auth-list-title" className="text-base font-semibold">
        {t("performFirst.activeTitle")}
      </h2>
      {list.isPending ? (
        <Skeleton className="h-16 w-full" />
      ) : items.length === 0 ? (
        <p className="text-sm text-muted">{t("performFirst.noneActive")}</p>
      ) : (
        <ul className="flex flex-col divide-y divide-border text-sm">
          {items.map((a) => (
            <li key={a.id} className="flex flex-wrap items-start justify-between gap-2 py-2.5">
              <div className="flex min-w-0 flex-col gap-1">
                <span className="flex flex-wrap items-center gap-2 font-medium">
                  {names.patient(a.patient)}
                  <bdi className="text-muted">{a.visit_number}</bdi>
                  <Badge variant="soft">{t(`performFirst.kinds.${a.kind}`)}</Badge>
                </span>
                <span className="text-muted">
                  {names.label(a.reason)} · {names.user(a.authorized_by)} ·{" "}
                  <DateText value={a.authorized_at} format="datetime" />
                </span>
                <span className="text-muted">{names.list(a.lines.map((l) => names.name(l.service)))}</span>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setRevoking(a);
                }}
              >
                {t("performFirst.revoke")}
              </Button>
            </li>
          ))}
        </ul>
      )}
      <Pager page={page} pageSize={PAGE_SIZE} count={list.data?.count ?? 0} onPage={setPage} />
      <NoteDialog
        open={revoking !== null}
        onOpenChange={(o) => {
          if (!o) setRevoking(null);
        }}
        title={t("performFirst.revokeTitle")}
        description={t("performFirst.revokeDescription")}
        label={t("common:reason.note")}
        confirmLabel={t("performFirst.revoke")}
        destructive
        onSubmit={(note) => revoke.mutateAsync({ authorizationId: revoking?.id ?? 0, note })}
      />
    </section>
  );
}
