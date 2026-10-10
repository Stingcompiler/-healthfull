import { zodResolver } from "@hookform/resolvers/zod";
import { Link } from "@tanstack/react-router";
import { Undo2 } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { z } from "zod";

import { AlertCard } from "@/components/AlertCard";
import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { Form, SelectField, TextareaField, TextField } from "@/components/form";
import { PageHeader } from "@/components/PageHeader";
import { SearchInput } from "@/components/SearchInput";
import { SecondApproverFields } from "@/components/SecondApproverFields";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";
import { usePermission } from "@/lib/auth/hooks";
import { vmsg } from "@/lib/validation";

import { PAGE_SIZE, usePharmacyOptions, useReturnableDispenses, useReturnUnits } from "../api";
import { ErrorAlert } from "../components/common";
import { PharmacyNav } from "../components/PharmacyNav";
import { useNames } from "../lib/use-names";
import type { ReturnableDispense, ReturnableLine } from "../types";

/** Stock-adjustment reasons that make sense for units coming back from a patient. */
const RETURN_REASONS = new Set(["PATIENT_RETURNED", "DISPENSED_IN_ERROR", "DAMAGED", "OTHER"]);

interface Target {
  dispense: ReturnableDispense;
  line: ReturnableLine;
}

/**
 * Dispense returns (FEATURES 8.4, ADR 0018): units a patient brings back go on the shelf in
 * the batch they left. A paid line's units need a second person's approval; the money goes
 * back at the cashier by a credit note, never here.
 */
export function ReturnsPage() {
  const { t } = useTranslation(["pharmacy", "errors"]);
  const translateError = useTranslateError();
  const names = useNames();
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const list = useReturnableDispenses(q, page);
  const [target, setTarget] = useState<Target | null>(null);
  const data = list.data;
  const pages = data ? Math.max(1, Math.ceil(data.count / PAGE_SIZE)) : 1;

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader title={t("returns.title")} description={t("returns.description")} icon={<Undo2 />} />
      <PharmacyNav />
      <SearchInput
        label={t("returns.search")}
        placeholder={t("returns.searchPlaceholder")}
        value={q}
        onValueChange={(v) => {
          setQ(v);
          setPage(1);
        }}
        loading={list.isFetching}
        className="w-full md:max-w-md"
        data-testid="returns-search"
      />
      {list.isError ? (
        <ErrorAlert message={translateError(list.error)} />
      ) : list.isPending || !data ? (
        <div className="grid gap-3" aria-busy="true">
          <Skeleton className="h-32" />
          <Skeleton className="h-32" />
        </div>
      ) : data.items.length === 0 ? (
        <EmptyState icon={<Undo2 />} title={t("returns.empty")} description={t("returns.emptyHint")} />
      ) : (
        <>
          <ul className="grid gap-3">
            {data.items.map((d) => (
              <li key={d.id} className="min-w-0">
                <article className="card-surface flex min-w-0 flex-col gap-3 p-4" data-testid="returnable-dispense">
                  <header className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <h2 className="text-base font-semibold text-pretty break-words text-fg">
                        {names.person(d.patient)}
                      </h2>
                      <p className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
                        <bdi className="tabular font-semibold text-fg">{d.patient.file_no}</bdi>
                        <bdi className="tabular">{d.number}</bdi>
                        <DateText value={d.dispensed_at} format="datetime" />
                      </p>
                    </div>
                    <span className="text-xs text-muted">{names.name(d.store)}</span>
                  </header>
                  <ul className="grid gap-2">
                    {d.lines.map((line) => (
                      <li
                        key={line.id}
                        className="flex min-w-0 flex-col gap-2 rounded-control border border-border p-3 sm:flex-row sm:items-center sm:justify-between"
                        data-testid="returnable-line"
                        data-line-id={line.id}
                      >
                        <div className="min-w-0">
                          <p className="font-medium text-pretty break-words text-fg">{names.name(line.service)}</p>
                          <p className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
                            <span>
                              {t("batch.number")}: <bdi>{line.batch_no}</bdi>
                            </span>
                            <span>{t("returns.given", { count: line.qty_base })}</span>
                            <span data-testid="line-returned">{t("returns.returned", { count: line.returned })}</span>
                          </p>
                          {line.needs_approver ? (
                            <Badge variant="info" className="mt-1">
                              {t("returns.paidBadge")}
                            </Badge>
                          ) : null}
                        </div>
                        <Button
                          variant="outline"
                          className="h-11 shrink-0"
                          disabled={line.returnable <= 0}
                          onClick={() => {
                            setTarget({ dispense: d, line });
                          }}
                          data-testid="return-open"
                        >
                          <Undo2 aria-hidden="true" className="rtl:-scale-x-100" />
                          {line.returnable > 0 ? t("returns.action") : t("returns.nothingLeft")}
                        </Button>
                      </li>
                    ))}
                  </ul>
                </article>
              </li>
            ))}
          </ul>
          {pages > 1 ? (
            <nav className="flex items-center justify-between gap-2" aria-label={t("returns.pages")}>
              <Button
                variant="outline"
                disabled={page <= 1}
                onClick={() => {
                  setPage((p) => p - 1);
                }}
              >
                {t("returns.previous")}
              </Button>
              <span className="tabular text-sm text-muted">{t("returns.page", { page, pages })}</span>
              <Button
                variant="outline"
                disabled={page >= pages}
                onClick={() => {
                  setPage((p) => p + 1);
                }}
              >
                {t("returns.next")}
              </Button>
            </nav>
          ) : null}
        </>
      )}
      <ReturnDialog
        target={target}
        onOpenChange={() => {
          setTarget(null);
        }}
      />
    </div>
  );
}

function schema(max: number, needsApprover: boolean) {
  const credential = needsApprover ? z.string().trim().min(1, vmsg("validation.required")) : z.string();
  return z.object({
    quantity: z
      .string()
      .trim()
      .refine((v) => /^\d+$/.test(v) && Number(v) >= 1 && Number(v) <= max, {
        message: vmsg("pharmacy:returns.quantityRange", { max }),
      }),
    reason: z.string().min(1, vmsg("validation.selectOption")),
    note: z.string().trim().max(300),
    creditNote: z.string(),
    username: credential,
    password: needsApprover ? z.string().min(1, vmsg("validation.required")) : z.string(),
  });
}

type Values = z.infer<ReturnType<typeof schema>>;

function ReturnDialog({ target, onOpenChange }: { target: Target | null; onOpenChange: (open: boolean) => void }) {
  const { t } = useTranslation("pharmacy");
  const names = useNames();
  return (
    <Dialog
      open={target !== null}
      onOpenChange={(open) => {
        if (!open) onOpenChange(false);
      }}
    >
      <DialogContent className="sm:max-w-lg" data-testid="return-dialog">
        <DialogHeader>
          <DialogTitle>{t("returns.dialogTitle")}</DialogTitle>
          {target ? (
            <DialogDescription>
              {t("returns.dialogDescription", {
                service: names.name(target.line.service),
                batch: target.line.batch_no,
              })}
            </DialogDescription>
          ) : null}
        </DialogHeader>
        {target ? (
          <ReturnForm
            key={target.line.id}
            target={target}
            onDone={() => {
              onOpenChange(false);
            }}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function ReturnForm({ target, onDone }: { target: Target; onDone: () => void }) {
  const { t } = useTranslation(["pharmacy", "common", "errors"]);
  const names = useNames();
  const translateError = useTranslateError();
  const options = usePharmacyOptions();
  const returnUnits = useReturnUnits();
  const canOpenCashier = usePermission("billing.view");
  const [error, setError] = useState<string | null>(null);
  const { line, dispense } = target;
  const form = useForm<Values>({
    resolver: zodResolver(schema(line.returnable, line.needs_approver)),
    defaultValues: { quantity: "1", reason: "", note: "", creditNote: "", username: "", password: "" },
  });
  const reasons = (options.data?.reasons_stock_adjust ?? []).filter((r) => RETURN_REASONS.has(r.code));

  const submit = form.handleSubmit(async (v) => {
    setError(null);
    try {
      await returnUnits.mutateAsync({
        dispenseLineId: line.id,
        body: {
          quantity: Number(v.quantity),
          reason_code: v.reason,
          note: v.note.trim(),
          credit_note_id: v.creditNote ? Number(v.creditNote) : null,
          approver: line.needs_approver ? { username: v.username.trim(), password: v.password } : null,
        },
      });
      toast.success(t("returns.savedToast", { count: Number(v.quantity) }));
      onDone();
    } catch (e) {
      setError(translateError(e));
    }
  });

  return (
    <Form {...form}>
      <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4">
        <p className="text-sm text-muted" data-testid="return-returnable">
          {t("returns.returnable", { count: line.returnable })}
        </p>
        <TextField
          control={form.control}
          name="quantity"
          label={t("returns.quantity")}
          type="number"
          inputMode="numeric"
          required
        />
        <SelectField
          control={form.control}
          name="reason"
          label={t("common:reason.code")}
          placeholder={t("common:reason.codePlaceholder")}
          options={reasons.map((r) => ({ value: r.code, label: names.label(r) }))}
          required
        />
        <TextareaField
          control={form.control}
          name="note"
          label={t("common:reason.note")}
          placeholder={t("common:reason.notePlaceholder")}
          rows={2}
          maxLength={300}
        />
        {line.credit_notes.length > 0 ? (
          <SelectField
            control={form.control}
            name="creditNote"
            label={t("returns.creditNote")}
            placeholder={t("returns.creditNoteNone")}
            options={line.credit_notes.map((c) => ({ value: String(c.id), label: c.number }))}
          />
        ) : null}
        {line.needs_approver ? (
          <>
            <AlertCard variant="info" title={t("returns.paidTitle")}>
              {t("returns.paidBody")}{" "}
              {canOpenCashier ? (
                <Link to="/cashier" search={{ visit: dispense.visit_id }} className="font-medium underline">
                  {t("returns.openCashier")}
                </Link>
              ) : null}
            </AlertCard>
            <SecondApproverFields
              control={form.control}
              usernameName="username"
              passwordName="password"
              hint={t("returns.approverHint")}
            />
          </>
        ) : null}
        {error ? (
          <AlertCard variant="danger" title={t("errors:title")} live>
            {error}
          </AlertCard>
        ) : null}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onDone}>
            {t("common:actions.cancel")}
          </Button>
          <Button type="submit" loading={form.formState.isSubmitting} data-testid="return-confirm">
            {t("returns.confirm")}
          </Button>
        </DialogFooter>
      </form>
    </Form>
  );
}
