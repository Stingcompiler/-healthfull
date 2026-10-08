import { zodResolver } from "@hookform/resolvers/zod";
import { useNavigate } from "@tanstack/react-router";
import type { ColumnDef } from "@tanstack/react-table";
import { Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { z } from "zod";

import { DataTable } from "@/components/DataTable";
import { DateText } from "@/components/DateText";
import { SelectField, TextField } from "@/components/form";
import { SearchInput } from "@/components/SearchInput";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { vmsg } from "@/lib/validation";

import { usePayers, useSavePayer } from "../api";
import { AdminPage, QueryState } from "../components/AdminPage";
import { FilterBar } from "../components/Filters";
import { ActiveBadge, Code, FormDialog } from "../components/FormDialog";
import { useLocalName } from "../hooks";
import { PAYER_KINDS, type PayerKind, type PayerListOut } from "../types";

const schema = z.object({
  code: z
    .string()
    .trim()
    .regex(/^[A-Z][A-Z0-9_-]{0,29}$/, vmsg("admin:common.codeRule")),
  name_ar: z.string().trim().min(1, vmsg("validation.required")).max(200),
  name_en: z.string().trim().min(1, vmsg("validation.required")).max(200),
  kind: z.enum(PAYER_KINDS as [PayerKind, ...PayerKind[]]),
});
type Values = z.infer<typeof schema>;

export function PayersPage() {
  const { t } = useTranslation("admin");
  const localName = useLocalName();
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [creating, setCreating] = useState(false);
  const payers = usePayers(q || undefined);

  const open = (payer: PayerListOut) => {
    void navigate({ to: "/administration/payers/$payerId", params: { payerId: String(payer.id) } });
  };

  const columns = useMemo<ColumnDef<PayerListOut>[]>(
    () => [
      {
        id: "name",
        accessorFn: (p) => localName(p),
        header: t("common.name"),
        meta: { label: t("common.name") },
        cell: ({ row }) => (
          <div className="min-w-0">
            <div className="truncate font-medium text-fg">{localName(row.original)}</div>
            <Code>{row.original.code}</Code>
          </div>
        ),
      },
      {
        accessorKey: "kind",
        header: t("payers.kind"),
        meta: { label: t("payers.kind") },
        cell: ({ row }) => <Badge variant="outline">{t(`payers.kinds.${row.original.kind}`)}</Badge>,
      },
      {
        id: "price_list",
        accessorFn: (p) => p.price_list_code ?? "",
        header: t("payers.priceList"),
        meta: { label: t("payers.priceList") },
        cell: ({ row }) =>
          row.original.price_list_code ? (
            <Code>{row.original.price_list_code}</Code>
          ) : (
            <span className="text-muted">{t("payers.cashList")}</span>
          ),
      },
      {
        id: "contract_end",
        accessorFn: (p) => p.contract_end ?? "",
        header: t("payers.contractEnd"),
        meta: { label: t("payers.contractEnd") },
        cell: ({ row }) => (row.original.contract_end ? <DateText value={row.original.contract_end} /> : "—"),
      },
      {
        accessorKey: "active",
        header: t("common.status"),
        meta: { label: t("common.status") },
        cell: ({ row }) => <ActiveBadge active={row.original.active} />,
      },
    ],
    [t, localName],
  );

  return (
    <AdminPage
      section="payers"
      title={t("sections.payers.title")}
      description={t("sections.payers.description")}
      actions={
        <Button
          onClick={() => {
            setCreating(true);
          }}
        >
          <Plus />
          {t("payers.add")}
        </Button>
      }
    >
      <FilterBar>
        <SearchInput
          label={t("payers.search")}
          placeholder={t("payers.search")}
          onSearch={setQ}
          className="sm:max-w-xs"
        />
      </FilterBar>
      <QueryState loading={payers.isPending} error={payers.error} onRetry={() => void payers.refetch()}>
        <DataTable
          caption={t("sections.payers.title")}
          columns={columns}
          data={payers.data?.items ?? []}
          getRowId={(p) => String(p.id)}
          onRowClick={open}
          rowLabel={(p) => t("payers.open", { name: localName(p) })}
        />
      </QueryState>
      {creating ? (
        <CreatePayerDialog
          onClose={() => {
            setCreating(false);
          }}
        />
      ) : null}
    </AdminPage>
  );
}

function CreatePayerDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation("admin");
  const navigate = useNavigate();
  const save = useSavePayer();
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { code: "", name_ar: "", name_en: "", kind: "insurance" },
  });
  return (
    <FormDialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={t("payers.add")}
      description={t("payers.addHint")}
      form={form}
      error={save.error}
      onSubmit={async (values) => {
        const payer = await save.mutateAsync({ body: values });
        toast.success(t("common.saved"));
        onClose();
        await navigate({ to: "/administration/payers/$payerId", params: { payerId: String(payer.id) } });
      }}
    >
      <TextField control={form.control} name="code" label={t("common.code")} dir="ltr" required />
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField control={form.control} name="name_ar" label={t("common.nameAr")} dir="rtl" required />
        <TextField control={form.control} name="name_en" label={t("common.nameEn")} dir="ltr" required />
      </div>
      <SelectField
        control={form.control}
        name="kind"
        label={t("payers.kind")}
        options={PAYER_KINDS.map((k) => ({ value: k, label: t(`payers.kinds.${k}`) }))}
      />
    </FormDialog>
  );
}
