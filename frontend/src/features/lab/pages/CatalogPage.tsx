import { zodResolver } from "@hookform/resolvers/zod";
import { useNavigate } from "@tanstack/react-router";
import type { ColumnDef } from "@tanstack/react-table";
import { BookOpen, Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { AlertCard } from "@/components/AlertCard";
import { DataTable, DataTableOpenButton } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { Form, SelectField, TextField } from "@/components/form";
import { PageHeader } from "@/components/PageHeader";
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
import { useTranslateError } from "@/lib/api/translate-error";
import { formatNumber } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";
import { vmsg } from "@/lib/validation";

import { useCreateTest, useLabTests, useUnlinkedServices } from "../api";
import { LabNav } from "../components/LabNav";
import { useLabNames } from "../lib/use-lab-names";
import { SAMPLE_TYPES, type LabTestListItem, type SampleType } from "../types";

/** The test catalog (FEATURES 9.1): every lab test with its sample and turnaround target. */
export function CatalogPage() {
  const { t } = useTranslation(["lab", "errors"]);
  const translateError = useTranslateError();
  const language = useLanguage();
  const names = useLabNames();
  const navigate = useNavigate();
  const tests = useLabTests();
  const [creating, setCreating] = useState(false);
  const open = (row: LabTestListItem) => {
    void navigate({ to: "/lab/catalog/$testId", params: { testId: String(row.id) } });
  };

  const columns = useMemo<ColumnDef<LabTestListItem>[]>(
    () => [
      {
        id: "name",
        header: t("catalog.columns.test"),
        meta: { label: t("catalog.columns.test"), className: "whitespace-normal" },
        cell: ({ row }) => (
          <span className="flex flex-col">
            <span className="font-medium">{names.test(row.original)}</span>
            <bdi className="text-xs text-muted">{row.original.code}</bdi>
          </span>
        ),
      },
      {
        id: "sample",
        header: t("catalog.columns.sample"),
        meta: { label: t("catalog.columns.sample") },
        cell: ({ row }) => t(`sampleType.${row.original.sample_type}`),
      },
      {
        id: "params",
        header: t("catalog.columns.parameters"),
        meta: { label: t("catalog.columns.parameters"), align: "end" },
        cell: ({ row }) => <span className="tabular">{formatNumber(row.original.parameter_count, language)}</span>,
      },
      {
        id: "tat",
        header: t("catalog.columns.turnaround"),
        meta: { label: t("catalog.columns.turnaround"), align: "end" },
        cell: ({ row }) => t("tat.minutes", { count: row.original.turnaround_minutes }),
      },
      {
        id: "status",
        header: t("catalog.columns.status"),
        meta: { label: t("catalog.columns.status") },
        cell: ({ row }) =>
          row.original.active ? (
            <Badge variant="success">{t("catalog.active")}</Badge>
          ) : (
            <Badge variant="neutral">{t("catalog.inactive")}</Badge>
          ),
      },
    ],
    [t, names, language],
  );

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader
        title={t("catalog.title")}
        description={t("catalog.description")}
        icon={<BookOpen />}
        actions={
          <Button
            onClick={() => {
              setCreating(true);
            }}
            data-testid="new-test"
          >
            <Plus aria-hidden="true" />
            {t("catalog.new")}
          </Button>
        }
      />
      <LabNav />
      {tests.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(tests.error)}
        </AlertCard>
      ) : (
        <DataTable
          columns={columns}
          data={tests.data ?? []}
          loading={tests.isPending}
          getRowId={(r) => String(r.id)}
          caption={t("catalog.title")}
          onRowClick={open}
          rowLabel={(r) => names.test(r)}
          pageSize={50}
          minTableWidth={640}
          emptyState={<EmptyState bare size="compact" icon={<BookOpen />} title={t("catalog.empty")} />}
          renderCard={(r, ctx) => (
            <div className="card-surface relative flex flex-col gap-1 p-4" data-testid="catalog-row">
              <span className="flex items-start justify-between gap-2">
                {ctx.open ? (
                  <DataTableOpenButton onOpen={ctx.open} label={ctx.openLabel} className="text-start font-semibold">
                    {names.test(r)}
                  </DataTableOpenButton>
                ) : (
                  <span className="font-semibold">{names.test(r)}</span>
                )}
                {r.active ? null : <Badge variant="neutral">{t("catalog.inactive")}</Badge>}
              </span>
              <span className="flex flex-wrap gap-x-3 text-xs text-muted">
                <bdi>{r.code}</bdi>
                <span>{t(`sampleType.${r.sample_type}`)}</span>
                <span>{t("catalog.parameterCount", { count: r.parameter_count })}</span>
              </span>
            </div>
          )}
        />
      )}
      <NewTestDialog
        open={creating}
        onOpenChange={setCreating}
        onCreated={(id) => {
          void navigate({ to: "/lab/catalog/$testId", params: { testId: String(id) } });
        }}
      />
    </div>
  );
}

const newTestSchema = z.object({
  service_id: z.string().min(1, vmsg("validation.selectOption")),
  code: z
    .string()
    .trim()
    .min(1, vmsg("validation.required"))
    .max(30)
    .regex(/^[A-Za-z0-9_-]+$/, vmsg("validation.invalid")),
  sample_type: z.string().min(1, vmsg("validation.selectOption")),
  container: z.string().trim().max(60),
  turnaround_minutes: z
    .string()
    .trim()
    .regex(/^[1-9][0-9]{0,4}$/, vmsg("validation.number")),
});

type NewTestValues = z.infer<typeof newTestSchema>;

function NewTestDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (id: number) => void;
}) {
  const { t } = useTranslation(["lab", "common", "errors"]);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="new-test-dialog">
        <DialogHeader>
          <DialogTitle>{t("catalog.newTitle")}</DialogTitle>
          <DialogDescription>{t("catalog.newDescription")}</DialogDescription>
        </DialogHeader>
        {open ? <NewTestForm onOpenChange={onOpenChange} onCreated={onCreated} /> : null}
      </DialogContent>
    </Dialog>
  );
}

function NewTestForm({
  onOpenChange,
  onCreated,
}: {
  onOpenChange: (open: boolean) => void;
  onCreated: (id: number) => void;
}) {
  const { t } = useTranslation(["lab", "common", "errors"]);
  const translateError = useTranslateError();
  const names = useLabNames();
  const services = useUnlinkedServices(true);
  const create = useCreateTest();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<NewTestValues>({
    resolver: zodResolver(newTestSchema),
    defaultValues: { service_id: "", code: "", sample_type: "", container: "", turnaround_minutes: "60" },
  });
  const submit = form.handleSubmit(async (v) => {
    setError(null);
    try {
      const made = await create.mutateAsync({
        service_id: Number(v.service_id),
        code: v.code.toUpperCase(),
        sample_type: v.sample_type as SampleType,
        container: v.container,
        method: "",
        instructions_ar: "",
        instructions_en: "",
        sort_order: 0,
        turnaround_minutes: Number(v.turnaround_minutes),
      });
      onOpenChange(false);
      onCreated(made.id);
    } catch (e) {
      setError(translateError(e));
    }
  });
  const options = (services.data ?? []).map((s) => ({ value: String(s.id), label: `${names.test(s)} (${s.code})` }));

  return (
    <Form {...form}>
      <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4">
        {services.data && options.length === 0 ? (
          <AlertCard variant="info" title={t("catalog.noServices")}>
            {t("catalog.noServicesHint")}
          </AlertCard>
        ) : null}
        <SelectField
          control={form.control}
          name="service_id"
          label={t("catalog.service")}
          placeholder={t("catalog.servicePlaceholder")}
          options={options}
          required
        />
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField control={form.control} name="code" label={t("catalog.code")} dir="ltr" maxLength={30} required />
          <SelectField
            control={form.control}
            name="sample_type"
            label={t("catalog.sampleType")}
            placeholder={t("entry.choose")}
            options={SAMPLE_TYPES.map((s) => ({ value: s, label: t(`sampleType.${s}`) }))}
            required
          />
          <TextField control={form.control} name="container" label={t("catalog.container")} maxLength={60} />
          <TextField
            control={form.control}
            name="turnaround_minutes"
            label={t("catalog.turnaround")}
            type="number"
            inputMode="numeric"
            dir="ltr"
            required
          />
        </div>
        {error ? (
          <AlertCard variant="danger" title={t("errors:title")} live>
            {error}
          </AlertCard>
        ) : null}
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              onOpenChange(false);
            }}
          >
            {t("common:actions.cancel")}
          </Button>
          <Button type="submit" loading={form.formState.isSubmitting} data-testid="create-test">
            {t("catalog.create")}
          </Button>
        </DialogFooter>
      </form>
    </Form>
  );
}
