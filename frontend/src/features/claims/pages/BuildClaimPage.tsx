import { useNavigate, useSearch } from "@tanstack/react-router";
import { FilePlus2 } from "lucide-react";
import { useId, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { MoneyText } from "@/components/MoneyText";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { sumAmounts } from "@/features/cashier/lib/money";
import { centerToday } from "@/features/patients/lib";
import { useTranslateError } from "@/lib/api/translate-error";

import { useAccrued, useBuildClaim, useClaimOptions } from "../api";
import { ClaimsNav } from "../components/ClaimsNav";
import { useClaimNames } from "../lib/names";
import type { ClaimsSearch } from "../lib/search";
import type { ClaimAccruedLine } from "../types";

/**
 * The claim batch builder (FEATURES 11.3): one payer, one period of invoice approval dates,
 * and the accrued payer shares to put on the claim (all ticked by default). Building makes a
 * draft claim; nothing is money yet (invariant 7).
 */
export function BuildClaimPage() {
  const { t } = useTranslation(["claims", "common", "errors"]);
  const translateError = useTranslateError();
  const names = useClaimNames();
  const navigate = useNavigate();
  const search: ClaimsSearch = useSearch({ strict: false });
  const options = useClaimOptions();
  const today = centerToday();
  const [payerId, setPayerId] = useState<number | undefined>(search.payer);
  const [start, setStart] = useState(`${today.slice(0, 8)}01`);
  const [end, setEnd] = useState(today);
  const [note, setNote] = useState("");
  const [excluded, setExcluded] = useState<ReadonlySet<number>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const periodValid = start !== "" && end !== "" && start <= end;
  const accrued = useAccrued(periodValid ? payerId : undefined, start, end);
  const build = useBuildClaim();
  const ids = useId();

  const items = useMemo(() => accrued.data?.items ?? [], [accrued.data]);
  const chosen = items.filter((i) => !excluded.has(i.invoice_line_id));
  const chosenTotal = sumAmounts(chosen.map((i) => i.amount)) ?? "0.00";
  const allChosen = items.length > 0 && chosen.length === items.length;
  const payers = (options.data?.payers ?? []).filter((p) => p.active || p.id === payerId);

  const toggle = (line: ClaimAccruedLine, on: boolean) => {
    setExcluded((prev) => {
      const next = new Set(prev);
      if (on) next.delete(line.invoice_line_id);
      else next.add(line.invoice_line_id);
      return next;
    });
  };

  const submit = async () => {
    if (payerId === undefined) return;
    setError(null);
    try {
      const claim = await build.mutateAsync({
        payer_id: payerId,
        period_start: start,
        period_end: end,
        invoice_line_ids: chosen.map((i) => i.invoice_line_id),
        note: note.trim(),
      });
      void navigate({ to: "/claims/$claimId", params: { claimId: String(claim.id) } });
    } catch (e) {
      setError(translateError(e));
    }
  };

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader title={t("build.title")} description={t("build.description")} icon={<FilePlus2 />} />
      <ClaimsNav />
      <section className="card-surface grid gap-4 p-4 md:grid-cols-3 md:p-5" aria-label={t("build.criteria")}>
        <div className="grid gap-2">
          <Label htmlFor={`${ids}-payer`}>{t("build.payer")}</Label>
          <Select
            value={payerId ? String(payerId) : ""}
            onValueChange={(v) => {
              setPayerId(Number(v));
              setExcluded(new Set());
              void navigate({ to: "/claims/new", search: { payer: Number(v) }, replace: true });
            }}
          >
            <SelectTrigger id={`${ids}-payer`} className="h-11 w-full" data-testid="build-payer">
              <SelectValue placeholder={t("build.choosePayer")} />
            </SelectTrigger>
            <SelectContent>
              {payers.map((p) => (
                <SelectItem key={p.id} value={String(p.id)}>
                  {names.name(p)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="grid gap-2">
          <Label htmlFor={`${ids}-start`}>{t("build.periodStart")}</Label>
          <Input
            id={`${ids}-start`}
            type="date"
            dir="ltr"
            value={start}
            max={end || undefined}
            onChange={(e) => {
              setStart(e.target.value);
              setExcluded(new Set());
            }}
            data-testid="build-start"
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor={`${ids}-end`}>{t("build.periodEnd")}</Label>
          <Input
            id={`${ids}-end`}
            type="date"
            dir="ltr"
            value={end}
            min={start || undefined}
            onChange={(e) => {
              setEnd(e.target.value);
              setExcluded(new Set());
            }}
            data-testid="build-end"
          />
        </div>
        {!periodValid ? (
          <p className="text-sm text-danger-fg md:col-span-3" role="alert">
            {t("validation.period")}
          </p>
        ) : null}
      </section>

      {payerId === undefined ? (
        <EmptyState icon={<FilePlus2 />} title={t("build.noPayer")} description={t("build.noPayerHint")} />
      ) : accrued.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(accrued.error)}
        </AlertCard>
      ) : accrued.isPending ? (
        <Skeleton className="h-48 w-full" />
      ) : items.length === 0 ? (
        <EmptyState icon={<FilePlus2 />} title={t("build.empty")} description={t("build.emptyHint")} />
      ) : (
        <section className="card-surface flex min-w-0 flex-col gap-3 p-4 md:p-5" aria-labelledby={`${ids}-lines`}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 id={`${ids}-lines`} className="text-base font-semibold">
              {t("build.lines", { count: items.length })}
            </h2>
            <label className="flex min-h-11 items-center gap-2 text-sm">
              <Checkbox
                checked={allChosen ? true : chosen.length === 0 ? false : "indeterminate"}
                onCheckedChange={(v) => {
                  setExcluded(v === true ? new Set() : new Set(items.map((i) => i.invoice_line_id)));
                }}
                data-testid="build-select-all"
              />
              {t("build.selectAll")}
            </label>
          </div>
          <ul className="flex flex-col divide-y divide-border" data-testid="accrued-lines">
            {items.map((line) => {
              const on = !excluded.has(line.invoice_line_id);
              const id = `${ids}-line-${String(line.invoice_line_id)}`;
              return (
                <li key={line.invoice_line_id} className="flex items-start gap-3 py-3" data-testid="accrued-line">
                  <Checkbox
                    id={id}
                    checked={on}
                    onCheckedChange={(v) => {
                      toggle(line, v === true);
                    }}
                    className="mt-1"
                    aria-describedby={`${id}-amount`}
                  />
                  <label
                    htmlFor={id}
                    className="flex min-w-0 flex-1 flex-col gap-1 sm:flex-row sm:items-start sm:gap-4"
                  >
                    <span className="flex min-w-0 flex-1 flex-col">
                      <span className="font-medium">{names.text(line.description_ar, line.description_en)}</span>
                      <span className="text-sm">{names.person(line.patient)}</span>
                      <span className="flex flex-wrap gap-x-3 text-xs text-muted">
                        <bdi>{line.patient.file_no}</bdi>
                        {line.card_number ? (
                          <span>
                            {t("build.card")}: <bdi>{line.card_number}</bdi>
                          </span>
                        ) : null}
                        <bdi>{line.invoice_number}</bdi>
                        <DateText value={line.approved_on} />
                        {line.pre_approval_ref ? (
                          <span>
                            {t("build.preApproval")}: <bdi>{line.pre_approval_ref}</bdi>
                          </span>
                        ) : null}
                      </span>
                    </span>
                    <span id={`${id}-amount`} className="flex flex-col sm:items-end">
                      <MoneyText value={line.amount} className="text-base" />
                      <span className="text-xs text-muted">{t("build.ageDays", { count: line.age_days })}</span>
                    </span>
                  </label>
                </li>
              );
            })}
          </ul>
          <div className="grid gap-2">
            <Label htmlFor={`${ids}-note`}>{t("build.note")}</Label>
            <Textarea
              id={`${ids}-note`}
              value={note}
              maxLength={500}
              onChange={(e) => {
                setNote(e.target.value);
              }}
            />
          </div>
          {error ? (
            <AlertCard variant="danger" title={t("errors:title")} live>
              {error}
            </AlertCard>
          ) : null}
          <div className="flex flex-col gap-3 border-t border-border pt-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="flex flex-wrap items-center gap-x-2 text-sm" data-testid="build-total">
              <span className="text-muted">{t("build.selected", { count: chosen.length })}</span>
              <MoneyText value={chosenTotal} className="text-base font-semibold" />
            </p>
            <Button
              onClick={() => void submit()}
              disabled={chosen.length === 0 || !periodValid}
              loading={build.isPending}
              data-testid="build-submit"
            >
              <FilePlus2 aria-hidden="true" />
              {t("build.submit")}
            </Button>
          </div>
        </section>
      )}
    </div>
  );
}
