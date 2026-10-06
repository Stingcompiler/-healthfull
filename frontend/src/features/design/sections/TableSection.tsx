import type { ColumnDef } from "@tanstack/react-table";
import { Ban, Eye, Printer } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { DataTable } from "@/components/DataTable";
import { DateText } from "@/components/DateText";
import { MoneyText } from "@/components/MoneyText";
import { StatusBadge } from "@/components/StatusBadge";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { compareDecimal } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

import { SAMPLE_LINES, type SampleLine } from "../sample-data";
import { Section } from "../Section";

type Mode = "auto" | "table" | "cards";

export function TableSection() {
  const { t } = useTranslation("design");
  const language = useLanguage();
  const [mode, setMode] = useState<Mode>("auto");
  const [loading, setLoading] = useState(false);
  const [empty, setEmpty] = useState(false);

  const columns = useMemo<ColumnDef<SampleLine>[]>(
    () => [
      {
        accessorKey: "fileNo",
        header: t("table.fileNo"),
        meta: { label: t("table.fileNo") },
        cell: ({ row }) => <bdi className="tabular font-medium">{row.original.fileNo}</bdi>,
      },
      {
        id: "patient",
        accessorFn: (row) => pickName(row.patient, language),
        header: t("table.patient"),
        meta: { label: t("table.patient") },
      },
      {
        id: "service",
        accessorFn: (row) => pickName(row.service, language),
        header: t("table.service"),
        meta: { label: t("table.service"), className: "max-w-64 truncate" },
      },
      {
        id: "amount",
        accessorKey: "amount",
        sortingFn: (a, b) => compareDecimal(a.original.amount, b.original.amount),
        header: t("table.amount"),
        meta: { label: t("table.amount"), align: "end" },
        cell: ({ row }) => <MoneyText value={row.original.amount} />,
      },
      {
        accessorKey: "status",
        header: t("table.status"),
        meta: { label: t("table.status") },
        cell: ({ row }) => <StatusBadge status={row.original.status} size="sm" />,
      },
      {
        accessorKey: "date",
        header: t("table.date"),
        meta: { label: t("table.date") },
        cell: ({ row }) => <DateText value={row.original.date} format="datetime" className="text-muted" />,
      },
    ],
    [t, language],
  );

  return (
    <Section id="table" title={t("sections.table")} description={t("descriptions.table")}>
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
        <Tabs
          value={mode}
          onValueChange={(v) => {
            setMode(v as Mode);
          }}
        >
          <TabsList aria-label={t("table.mode")}>
            <TabsTrigger value="auto">{t("table.modeAuto")}</TabsTrigger>
            <TabsTrigger value="table">{t("table.modeTable")}</TabsTrigger>
            <TabsTrigger value="cards">{t("table.modeCards")}</TabsTrigger>
          </TabsList>
        </Tabs>
        <div className="flex items-center gap-2">
          <Switch id="ds-table-loading" checked={loading} onCheckedChange={setLoading} />
          <Label htmlFor="ds-table-loading">{t("table.showLoading")}</Label>
        </div>
        <div className="flex items-center gap-2">
          <Switch id="ds-table-empty" checked={empty} onCheckedChange={setEmpty} />
          <Label htmlFor="ds-table-empty">{t("table.showEmpty")}</Label>
        </div>
      </div>
      <DataTable
        caption={t("table.caption")}
        columns={columns}
        data={empty ? [] : SAMPLE_LINES}
        getRowId={(row) => row.id}
        loading={loading}
        mode={mode}
        pageSize={5}
        pageSizeOptions={[5, 10, 25]}
        initialSorting={[{ id: "date", desc: true }]}
        rowActions={(row) => [
          {
            label: t("table.view"),
            icon: <Eye />,
            onSelect: () => toast.info(t("table.viewing", { id: row.id })),
          },
          { label: t("table.print"), icon: <Printer />, onSelect: () => undefined },
          {
            label: t("table.cancelLine"),
            icon: <Ban />,
            destructive: true,
            separated: true,
            disabled: row.status === "cancelled" || row.status === "performed",
            onSelect: () => undefined,
          },
        ]}
        renderCard={(row, { actions }) => (
          <div className="card-surface flex flex-col gap-3 p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="truncate font-semibold text-fg">{pickName(row.service, language)}</div>
                <div className="mt-0.5 truncate text-sm text-muted">
                  {pickName(row.patient, language)} · <bdi className="tabular">{row.fileNo}</bdi>
                </div>
              </div>
              {actions}
            </div>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <StatusBadge status={row.status} size="sm" />
              <MoneyText value={row.amount} className="font-semibold text-fg" />
            </div>
            <DateText value={row.date} format="datetime" className="text-xs text-muted" />
          </div>
        )}
      />
    </Section>
  );
}
