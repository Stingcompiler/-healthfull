import { zodResolver } from "@hookform/resolvers/zod";
import type { ColumnDef } from "@tanstack/react-table";
import { Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { z } from "zod";

import { DataTable } from "@/components/DataTable";
import { SelectField, SwitchField, TextareaField, TextField } from "@/components/form";
import { SearchInput } from "@/components/SearchInput";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { vmsg } from "@/lib/validation";

import { useCategories, useDepartments, useSaveService, useServices, type ServiceFilters } from "../api";
import { AdminPage, QueryState } from "../components/AdminPage";
import { FilterBar, FilterSelect } from "../components/Filters";
import { ActiveBadge, Code, FormDialog } from "../components/FormDialog";
import { useLocalName } from "../hooks";
import { SERVICE_KINDS, type ServiceKind, type ServiceOut } from "../types";

const NONE = "__none__";

const schema = z
  .object({
    code: z
      .string()
      .trim()
      .regex(/^[A-Z0-9][A-Z0-9_.-]{0,39}$/, vmsg("admin:catalog.codeRule")),
    name_ar: z.string().trim().max(200),
    name_en: z.string().trim().max(200),
    kind: z.enum(SERVICE_KINDS as [ServiceKind, ...ServiceKind[]]),
    department: z.string(),
    category: z.string(),
    description: z.string().max(2000),
    sort_order: z.string().regex(/^\d{1,9}$/, vmsg("validation.number")),
    active: z.boolean(),
  })
  .refine((v) => v.name_ar !== "" || v.name_en !== "", {
    path: ["name_ar"],
    message: vmsg("admin:catalog.nameRequired"),
  });
type Values = z.infer<typeof schema>;

export function KindBadge({ kind }: { kind: ServiceKind }) {
  const { t } = useTranslation("admin");
  return <Badge variant="outline">{t(`kinds.${kind}`)}</Badge>;
}

export function CatalogPage() {
  const { t } = useTranslation("admin");
  const localName = useLocalName();
  const [filters, setFilters] = useState<ServiceFilters>({});
  const [editing, setEditing] = useState<ServiceOut | "new" | null>(null);
  const services = useServices(filters);
  const departments = useDepartments();

  const columns = useMemo<ColumnDef<ServiceOut>[]>(
    () => [
      {
        id: "name",
        accessorFn: (s) => localName(s),
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
        header: t("catalog.kind"),
        meta: { label: t("catalog.kind") },
        cell: ({ row }) => <KindBadge kind={row.original.kind} />,
      },
      {
        id: "department",
        accessorFn: (s) => s.department_code ?? "",
        header: t("departments.department"),
        meta: { label: t("departments.department") },
        cell: ({ row }) => (row.original.department_code ? <Code>{row.original.department_code}</Code> : "—"),
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
      section="catalog"
      title={t("sections.catalog.title")}
      description={t("sections.catalog.description")}
      actions={
        <Button
          onClick={() => {
            setEditing("new");
          }}
        >
          <Plus />
          {t("catalog.add")}
        </Button>
      }
    >
      <FilterBar>
        <SearchInput
          label={t("catalog.search")}
          placeholder={t("catalog.search")}
          onSearch={(q) => {
            setFilters((f) => ({ ...f, q: q || undefined }));
          }}
          className="sm:max-w-xs"
        />
        <FilterSelect
          label={t("catalog.kind")}
          allLabel={t("catalog.allKinds")}
          value={filters.kind}
          onChange={(kind) => {
            setFilters((f) => ({ ...f, kind: kind as ServiceKind | undefined }));
          }}
          options={SERVICE_KINDS.map((k) => ({ value: k, label: t(`kinds.${k}`) }))}
        />
        <FilterSelect
          label={t("departments.department")}
          allLabel={t("catalog.allDepartments")}
          value={filters.department_id === undefined ? undefined : String(filters.department_id)}
          onChange={(id) => {
            setFilters((f) => ({ ...f, department_id: id === undefined ? undefined : Number(id) }));
          }}
          options={(departments.data ?? []).map((d) => ({ value: String(d.id), label: localName(d) }))}
        />
      </FilterBar>
      <QueryState loading={services.isPending} error={services.error} onRetry={() => void services.refetch()}>
        <DataTable
          caption={t("sections.catalog.title")}
          columns={columns}
          data={services.data?.items ?? []}
          getRowId={(s) => String(s.id)}
          onRowClick={setEditing}
          rowLabel={(s) => t("common.editNamed", { name: localName(s) })}
          pageSize={25}
        />
      </QueryState>
      {editing ? (
        <ServiceDialog
          service={editing === "new" ? null : editing}
          onClose={() => {
            setEditing(null);
          }}
        />
      ) : null}
    </AdminPage>
  );
}

function ServiceDialog({ service, onClose }: { service: ServiceOut | null; onClose: () => void }) {
  const { t } = useTranslation("admin");
  const localName = useLocalName();
  const save = useSaveService();
  const departments = useDepartments();
  const categories = useCategories();
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      code: service?.code ?? "",
      name_ar: service?.name_ar ?? "",
      name_en: service?.name_en ?? "",
      kind: service?.kind ?? "procedure",
      department: service?.department_id ? String(service.department_id) : NONE,
      category: service?.category_id ? String(service.category_id) : NONE,
      description: service?.description ?? "",
      sort_order: String(service?.sort_order ?? 0),
      active: service?.active ?? true,
    },
  });
  const none = { value: NONE, label: t("common.none") };
  return (
    <FormDialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={service ? t("catalog.edit") : t("catalog.add")}
      form={form}
      error={save.error}
      wide
      onSubmit={async (values) => {
        const body = {
          name_ar: values.name_ar,
          name_en: values.name_en,
          department_id: values.department === NONE ? null : Number(values.department),
          category_id: values.category === NONE ? null : Number(values.category),
          description: values.description,
          sort_order: Number(values.sort_order),
          active: values.active,
        };
        await save.mutateAsync(
          service ? { id: service.id, body } : { body: { ...body, code: values.code, kind: values.kind } },
        );
        toast.success(t("common.saved"));
        onClose();
      }}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField
          control={form.control}
          name="code"
          label={t("common.code")}
          dir="ltr"
          disabled={service !== null}
          required
        />
        <SelectField
          control={form.control}
          name="kind"
          label={t("catalog.kind")}
          disabled={service !== null}
          description={service ? t("catalog.kindFixed") : undefined}
          options={SERVICE_KINDS.map((k) => ({ value: k, label: t(`kinds.${k}`) }))}
          required
        />
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField control={form.control} name="name_ar" label={t("common.nameAr")} dir="rtl" />
        <TextField control={form.control} name="name_en" label={t("common.nameEn")} dir="ltr" />
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <SelectField
          control={form.control}
          name="department"
          label={t("departments.department")}
          options={[
            none,
            ...(departments.data ?? [])
              .filter((d) => d.active)
              .map((d) => ({ value: String(d.id), label: localName(d) })),
          ]}
        />
        <SelectField
          control={form.control}
          name="category"
          label={t("catalog.category")}
          options={[
            none,
            ...(categories.data ?? [])
              .filter((c) => c.active)
              .map((c) => ({ value: String(c.id), label: localName(c) })),
          ]}
        />
      </div>
      <TextareaField control={form.control} name="description" label={t("catalog.description")} rows={2} />
      <TextField control={form.control} name="sort_order" label={t("common.sortOrder")} inputMode="numeric" dir="ltr" />
      <SwitchField control={form.control} name="active" label={t("common.active")} />
    </FormDialog>
  );
}
