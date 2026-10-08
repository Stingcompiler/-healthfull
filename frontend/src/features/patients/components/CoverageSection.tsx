import { zodResolver } from "@hookform/resolvers/zod";
import { Pencil, Plus, ShieldCheck, ShieldOff } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { z } from "zod";

import { AlertCard } from "@/components/AlertCard";
import { Can } from "@/components/Can";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { DateText } from "@/components/DateText";
import {
  CheckboxField,
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
  SelectField,
  TextField,
} from "@/components/form";
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
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { toApiError } from "@/lib/api/errors";
import { useTranslateError } from "@/lib/api/translate-error";
import { usePermission } from "@/lib/auth/hooks";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";
import { vmsg } from "@/lib/validation";

import { useAddCoverage, useCoverages, useEndCoverage, usePayers, useUpdateCoverage } from "../api";
import { QueryErrorAlert } from "./QueryErrorAlert";
import type { Coverage } from "../types";

const schema = z.object({
  payer_id: z.string().min(1, vmsg("validation.selectOption")),
  card_number: z.string().trim().max(60),
  member_name: z.string().trim().max(200),
  relation: z.string().trim().max(30),
  valid_from: z.string(),
  valid_to: z.string(),
  patient_percent_override: z
    .string()
    .trim()
    .refine((v) => v === "" || /^\d{1,3}(\.\d{1,2})?$/.test(v), vmsg("validation.number")),
  is_default: z.boolean(),
});
type Values = z.infer<typeof schema>;

const EMPTY: Values = {
  payer_id: "",
  card_number: "",
  member_name: "",
  relation: "",
  valid_from: "",
  valid_to: "",
  patient_percent_override: "",
  is_default: true,
};

function fromCoverage(c: Coverage): Values {
  return {
    payer_id: String(c.payer.id),
    card_number: c.card_number,
    member_name: c.member_name,
    relation: c.relation,
    valid_from: c.valid_from ?? "",
    valid_to: c.valid_to ?? "",
    patient_percent_override: c.patient_percent_override ?? "",
    is_default: c.is_default,
  };
}

/** Coverage on file (FEATURES 1.6): payer, card, validity, member share; add, edit, end. */
export function CoverageSection({ patientId, readOnly = false }: { patientId: number; readOnly?: boolean }) {
  const { t } = useTranslation(["patients", "common"]);
  const language = useLanguage();
  const translateError = useTranslateError();
  const coverages = useCoverages(patientId);
  const end = useEndCoverage();
  const canManage = usePermission("patients.manage_coverage") && !readOnly;
  const [editing, setEditing] = useState<Coverage | "new" | null>(null);
  const [ending, setEnding] = useState<Coverage | null>(null);
  const rows = coverages.data ?? [];

  return (
    <section aria-labelledby="coverage-heading" className="card-surface flex flex-col gap-3 p-4 md:p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="coverage-heading" className="flex items-center gap-2 text-base font-semibold text-fg">
          <ShieldCheck className="size-5 text-muted" aria-hidden="true" />
          {t("coverage.title")}
        </h2>
        {canManage ? (
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              setEditing("new");
            }}
          >
            <Plus aria-hidden="true" />
            {t("coverage.add")}
          </Button>
        ) : null}
      </div>
      {coverages.isError ? (
        <QueryErrorAlert
          title={t("coverage.loadFailed")}
          error={coverages.error}
          onRetry={() => void coverages.refetch()}
          retrying={coverages.isFetching}
        />
      ) : coverages.isPending ? (
        <Skeleton className="h-16" />
      ) : rows.length === 0 ? (
        <p className="text-sm text-muted">{t("coverage.none")}</p>
      ) : (
        <ul className="grid gap-2">
          {rows.map((c) => (
            <li
              key={c.id}
              className="flex min-w-0 flex-wrap items-start gap-3 rounded-control border border-border p-3"
              data-testid="coverage"
            >
              <div className="min-w-0 flex-1">
                <p className="flex flex-wrap items-center gap-2 font-medium text-fg">
                  {pickName({ ar: c.payer.name_ar, en: c.payer.name_en }, language)}
                  {c.is_default ? <Badge variant="info">{t("coverage.default")}</Badge> : null}
                </p>
                <p className="text-xs text-muted">
                  {c.card_number ? (
                    <>
                      {t("coverage.card")} <bdi className="tabular">{c.card_number}</bdi>
                    </>
                  ) : (
                    t("coverage.noCard")
                  )}
                  {c.patient_percent_override
                    ? ` · ${t("coverage.memberShare", { percent: c.patient_percent_override })}`
                    : null}
                </p>
                {c.valid_from || c.valid_to ? (
                  <p className="text-xs text-muted">
                    {t("coverage.validity")}{" "}
                    {c.valid_from ? <DateText value={c.valid_from} /> : t("coverage.openEnded")}
                    {" – "}
                    {c.valid_to ? <DateText value={c.valid_to} /> : t("coverage.openEnded")}
                  </p>
                ) : null}
              </div>
              {canManage ? (
                <div className="flex gap-1">
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    aria-label={t("coverage.editFor", {
                      payer: pickName({ ar: c.payer.name_ar, en: c.payer.name_en }, language),
                    })}
                    onClick={() => {
                      setEditing(c);
                    }}
                  >
                    <Pencil aria-hidden="true" />
                  </Button>
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    aria-label={t("coverage.endFor", {
                      payer: pickName({ ar: c.payer.name_ar, en: c.payer.name_en }, language),
                    })}
                    onClick={() => {
                      setEnding(c);
                    }}
                  >
                    <ShieldOff aria-hidden="true" />
                  </Button>
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      <Can permission="patients.manage_coverage">
        <CoverageDialog
          patientId={patientId}
          coverage={editing}
          onOpenChange={(open) => {
            if (!open) setEditing(null);
          }}
        />
      </Can>
      <ConfirmDialog
        open={ending !== null}
        onOpenChange={(open) => {
          if (!open) setEnding(null);
        }}
        title={t("coverage.endTitle")}
        description={t("coverage.endDescription")}
        confirmLabel={t("coverage.end")}
        destructive
        onConfirm={async () => {
          if (!ending) return;
          try {
            await end.mutateAsync(ending.id);
            toast.success(t("coverage.ended"));
          } catch (e) {
            toast.error(translateError(toApiError(e)));
          }
        }}
      />
    </section>
  );
}

function CoverageDialog({
  patientId,
  coverage,
  onOpenChange,
}: {
  patientId: number;
  coverage: Coverage | "new" | null;
  onOpenChange: (open: boolean) => void;
}) {
  return coverage === null ? null : (
    <CoverageForm patientId={patientId} coverage={coverage} onOpenChange={onOpenChange} />
  );
}

function CoverageForm({
  patientId,
  coverage,
  onOpenChange,
}: {
  patientId: number;
  coverage: Coverage | "new";
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation(["patients", "common", "errors"]);
  const language = useLanguage();
  const translateError = useTranslateError();
  const payers = usePayers();
  const add = useAddCoverage(patientId);
  const update = useUpdateCoverage();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: coverage === "new" ? EMPTY : fromCoverage(coverage),
  });
  const isNew = coverage === "new";

  const submit = form.handleSubmit(async (v) => {
    setError(null);
    const common = {
      card_number: v.card_number,
      member_name: v.member_name,
      relation: v.relation,
      valid_from: v.valid_from || null,
      valid_to: v.valid_to || null,
      patient_percent_override: v.patient_percent_override === "" ? null : v.patient_percent_override,
      is_default: v.is_default,
    };
    try {
      if (coverage === "new") await add.mutateAsync({ payer_id: Number(v.payer_id), ...common });
      else await update.mutateAsync({ id: coverage.id, body: common });
      toast.success(t("coverage.saved"));
      onOpenChange(false);
    } catch (e) {
      setError(translateError(toApiError(e)));
    }
  });

  const dateField = (name: "valid_from" | "valid_to", label: string) => (
    <FormField
      control={form.control}
      name={name}
      render={({ field }) => (
        <FormItem>
          <FormLabel>{label}</FormLabel>
          <FormControl>
            <Input type="date" dir="ltr" max="9999-12-31" {...field} />
          </FormControl>
          <FormMessage />
        </FormItem>
      )}
    />
  );

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>{isNew ? t("coverage.addTitle") : t("coverage.editTitle")}</DialogTitle>
          <DialogDescription>{t("coverage.dialogDescription")}</DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4 sm:grid-cols-2">
            <SelectField
              control={form.control}
              name="payer_id"
              label={t("coverage.payer")}
              placeholder={t("coverage.payerPlaceholder")}
              required
              disabled={!isNew}
              className="sm:col-span-2"
              options={(payers.data ?? []).map((p) => ({
                value: String(p.id),
                label: pickName({ ar: p.name_ar, en: p.name_en }, language),
              }))}
            />
            <TextField control={form.control} name="card_number" label={t("coverage.cardNumber")} dir="ltr" />
            <TextField control={form.control} name="member_name" label={t("coverage.memberName")} />
            <TextField control={form.control} name="relation" label={t("coverage.relation")} />
            <TextField
              control={form.control}
              name="patient_percent_override"
              label={t("coverage.percentOverride")}
              description={t("coverage.percentHint")}
              inputMode="decimal"
              dir="ltr"
            />
            {dateField("valid_from", t("coverage.validFrom"))}
            {dateField("valid_to", t("coverage.validTo"))}
            <CheckboxField
              control={form.control}
              name="is_default"
              label={t("coverage.makeDefault")}
              className="sm:col-span-2"
            />
            {error ? (
              <AlertCard variant="danger" title={t("errors:title")} live className="sm:col-span-2">
                {error}
              </AlertCard>
            ) : null}
            <DialogFooter className="sm:col-span-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  onOpenChange(false);
                }}
              >
                {t("common:actions.cancel")}
              </Button>
              <Button type="submit" loading={add.isPending || update.isPending}>
                {t("common:actions.save")}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
