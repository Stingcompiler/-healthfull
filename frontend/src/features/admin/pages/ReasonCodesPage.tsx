import { zodResolver } from "@hookform/resolvers/zod";
import type { ColumnDef } from "@tanstack/react-table";
import { Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { z } from "zod";

import { DataTable } from "@/components/DataTable";
import { SwitchField, TextField } from "@/components/form";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";
import { vmsg } from "@/lib/validation";

import { useReasonCodes, useSaveReasonCode } from "../api";
import { AdminPage, QueryState } from "../components/AdminPage";
import { ActiveBadge, Code, FormDialog } from "../components/FormDialog";
import { REASON_CATEGORIES, type ReasonCategory, type ReasonCodeOut } from "../types";

const schema = z.object({
  code: z
    .string()
    .trim()
    .regex(/^[A-Z][A-Z0-9_]{0,39}$/, vmsg("admin:reasons.codeRule")),
  label_ar: z.string().trim().min(1, vmsg("validation.required")).max(200),
  label_en: z.string().trim().min(1, vmsg("validation.required")).max(200),
  requires_note: z.boolean(),
  active: z.boolean(),
  sort_order: z.string().regex(/^\d{1,5}$/, vmsg("validation.number")),
});
type Values = z.infer<typeof schema>;

export function ReasonCodesPage() {
  const { t } = useTranslation("admin");
  const language = useLanguage();
  const [category, setCategory] = useState<ReasonCategory>("line_cancel");
  const reasons = useReasonCodes(category);
  const [editing, setEditing] = useState<ReasonCodeOut | "new" | null>(null);
  const label = (r: ReasonCodeOut) => pickName({ ar: r.label_ar, en: r.label_en }, language);

  const columns = useMemo<ColumnDef<ReasonCodeOut>[]>(
    () => [
      {
        id: "label",
        accessorFn: (r) => label(r),
        header: t("reasons.label"),
        meta: { label: t("reasons.label") },
        cell: ({ row }) => (
          <div className="min-w-0">
            <div className="font-medium text-fg">{label(row.original)}</div>
            <Code>{row.original.code}</Code>
          </div>
        ),
      },
      {
        accessorKey: "requires_note",
        header: t("reasons.requiresNote"),
        meta: { label: t("reasons.requiresNote") },
        cell: ({ row }) =>
          row.original.requires_note ? (
            <Badge variant="info">{t("reasons.noteRequired")}</Badge>
          ) : (
            <span className="text-muted">—</span>
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
    // eslint-disable-next-line react-hooks/exhaustive-deps -- label depends on the language only
    [t, language],
  );

  return (
    <AdminPage
      section="reasonCodes"
      title={t("sections.reasonCodes.title")}
      description={t("sections.reasonCodes.description")}
      actions={
        <Button
          onClick={() => {
            setEditing("new");
          }}
        >
          <Plus />
          {t("reasons.add")}
        </Button>
      }
    >
      <div className="grid gap-1.5 sm:max-w-sm">
        <Label htmlFor="reason-category">{t("reasons.category")}</Label>
        <Select
          value={category}
          onValueChange={(v) => {
            setCategory(v as ReasonCategory);
          }}
        >
          <SelectTrigger id="reason-category">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {REASON_CATEGORIES.map((c) => (
              <SelectItem key={c} value={c}>
                {t(`reasons.categories.${c}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <QueryState loading={reasons.isPending} error={reasons.error} onRetry={() => void reasons.refetch()}>
        <DataTable
          caption={t(`reasons.categories.${category}`)}
          columns={columns}
          data={reasons.data ?? []}
          getRowId={(r) => String(r.id)}
          onRowClick={setEditing}
          rowLabel={(r) => t("common.editNamed", { name: label(r) })}
          pageSize={50}
        />
      </QueryState>
      {editing ? (
        <ReasonDialog
          category={category}
          reason={editing === "new" ? null : editing}
          onClose={() => {
            setEditing(null);
          }}
        />
      ) : null}
    </AdminPage>
  );
}

function ReasonDialog({
  category,
  reason,
  onClose,
}: {
  category: ReasonCategory;
  reason: ReasonCodeOut | null;
  onClose: () => void;
}) {
  const { t } = useTranslation("admin");
  const save = useSaveReasonCode();
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      code: reason?.code ?? "",
      label_ar: reason?.label_ar ?? "",
      label_en: reason?.label_en ?? "",
      requires_note: reason?.requires_note ?? false,
      active: reason?.active ?? true,
      sort_order: String(reason?.sort_order ?? 0),
    },
  });
  return (
    <FormDialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={reason ? t("reasons.edit") : t("reasons.add")}
      description={t(`reasons.categories.${category}`)}
      form={form}
      error={save.error}
      onSubmit={async ({ code, sort_order, active, ...rest }) => {
        const order = Number(sort_order);
        await save.mutateAsync(
          reason
            ? { id: reason.id, body: { ...rest, active, sort_order: order } }
            : { body: { ...rest, code, category, sort_order: order } },
        );
        toast.success(t("common.saved"));
        onClose();
      }}
    >
      <TextField
        control={form.control}
        name="code"
        label={t("common.code")}
        dir="ltr"
        disabled={reason !== null}
        required
      />
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField control={form.control} name="label_ar" label={t("reasons.labelAr")} dir="rtl" required />
        <TextField control={form.control} name="label_en" label={t("reasons.labelEn")} dir="ltr" required />
      </div>
      <TextField control={form.control} name="sort_order" label={t("common.sortOrder")} inputMode="numeric" dir="ltr" />
      <SwitchField control={form.control} name="requires_note" label={t("reasons.requiresNote")} />
      {reason ? <SwitchField control={form.control} name="active" label={t("common.active")} /> : null}
    </FormDialog>
  );
}
