import { zodResolver } from "@hookform/resolvers/zod";
import type { ColumnDef } from "@tanstack/react-table";
import { Landmark, Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { z } from "zod";

import { DataTable } from "@/components/DataTable";
import { SwitchField, TextField } from "@/components/form";
import { Button } from "@/components/ui/button";
import { vmsg } from "@/lib/validation";

import { useBanks, useSaveBank } from "../api";
import { AdminPage, QueryState } from "../components/AdminPage";
import { ActiveBadge, Code, FormDialog } from "../components/FormDialog";
import { ListEmpty } from "../components/ListEmpty";
import { useLocalName } from "../hooks";
import type { BankOut } from "../types";

const schema = z.object({
  code: z
    .string()
    .trim()
    .regex(/^[A-Z][A-Z0-9_-]{0,19}$/, vmsg("admin:common.codeRule")),
  name_ar: z.string().trim().min(1, vmsg("validation.required")).max(150),
  name_en: z.string().trim().min(1, vmsg("validation.required")).max(150),
  sort_order: z.string().regex(/^\d{1,5}$/),
  active: z.boolean(),
});
type Values = z.infer<typeof schema>;

/**
 * Banks and wallets that transfer, QR and card payments name (FEATURES 6.1). A bank's code never
 * changes and a bank is never deleted: deactivating it takes it off the cashier's list while its
 * payments keep it (the reference is unique per bank).
 */
export function BanksPage() {
  const { t } = useTranslation("admin");
  const localName = useLocalName();
  const banks = useBanks();
  const [editing, setEditing] = useState<BankOut | "new" | null>(null);
  const columns = useMemo<ColumnDef<BankOut>[]>(
    () => [
      {
        id: "name",
        accessorFn: (b) => localName(b),
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
        accessorKey: "sort_order",
        header: t("common.sortOrder"),
        meta: { label: t("common.sortOrder"), align: "end" },
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
      section="banks"
      title={t("sections.banks.title")}
      description={t("sections.banks.description")}
      actions={
        <Button
          onClick={() => {
            setEditing("new");
          }}
        >
          <Plus />
          {t("banks.add")}
        </Button>
      }
    >
      <QueryState loading={banks.isPending} error={banks.error} onRetry={() => void banks.refetch()}>
        <DataTable
          caption={t("sections.banks.title")}
          columns={columns}
          data={banks.data ?? []}
          getRowId={(b) => String(b.id)}
          emptyState={
            <ListEmpty
              icon={<Landmark />}
              title={t("banks.emptyTitle")}
              description={t("banks.emptyDescription")}
              actionLabel={t("banks.add")}
              onAction={() => {
                setEditing("new");
              }}
            />
          }
          onRowClick={setEditing}
          rowLabel={(b) => t("common.editNamed", { name: localName(b) })}
        />
      </QueryState>
      {editing ? (
        <BankDialog
          bank={editing === "new" ? null : editing}
          onClose={() => {
            setEditing(null);
          }}
        />
      ) : null}
    </AdminPage>
  );
}

function BankDialog({ bank, onClose }: { bank: BankOut | null; onClose: () => void }) {
  const { t } = useTranslation("admin");
  const save = useSaveBank();
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      code: bank?.code ?? "",
      name_ar: bank?.name_ar ?? "",
      name_en: bank?.name_en ?? "",
      sort_order: String(bank?.sort_order ?? 0),
      active: bank?.active ?? true,
    },
  });
  return (
    <FormDialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={bank ? t("banks.edit") : t("banks.add")}
      description={t("banks.hint")}
      form={form}
      error={save.error}
      onSubmit={async ({ code, sort_order, ...rest }) => {
        const body = { ...rest, sort_order: Number(sort_order) };
        await save.mutateAsync(bank ? { id: bank.id, body } : { body: { ...body, code } });
        toast.success(t("common.saved"));
        onClose();
      }}
    >
      <TextField
        control={form.control}
        name="code"
        label={t("common.code")}
        dir="ltr"
        disabled={bank !== null}
        required
      />
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField control={form.control} name="name_ar" label={t("common.nameAr")} dir="rtl" required />
        <TextField control={form.control} name="name_en" label={t("common.nameEn")} dir="ltr" required />
      </div>
      <TextField control={form.control} name="sort_order" label={t("common.sortOrder")} inputMode="numeric" dir="ltr" />
      <SwitchField
        control={form.control}
        name="active"
        label={t("common.active")}
        description={t("banks.activeHint")}
      />
    </FormDialog>
  );
}
