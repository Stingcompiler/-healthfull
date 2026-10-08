import { zodResolver } from "@hookform/resolvers/zod";
import { Link, useNavigate } from "@tanstack/react-router";
import { CalendarClock, Plus, Tags } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { z } from "zod";

import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { SelectField, TextField } from "@/components/form";
import { ChevronNext } from "@/components/icons";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { vmsg } from "@/lib/validation";

import { useCreatePriceList, usePriceLists } from "../api";
import { AdminPage, QueryState } from "../components/AdminPage";
import { ActiveBadge, Code, FormDialog } from "../components/FormDialog";
import { useLocalName } from "../hooks";
import type { PriceListOut } from "../types";

const schema = z.object({
  code: z
    .string()
    .trim()
    .regex(/^[A-Z][A-Z0-9_-]{0,29}$/, vmsg("admin:common.codeRule")),
  name_ar: z.string().trim().min(1, vmsg("validation.required")).max(150),
  name_en: z.string().trim().min(1, vmsg("validation.required")).max(150),
  kind: z.enum(["cash", "payer"]),
});
type Values = z.infer<typeof schema>;

export function PriceListsPage() {
  const { t } = useTranslation("admin");
  const lists = usePriceLists();
  const [creating, setCreating] = useState(false);
  return (
    <AdminPage
      section="priceLists"
      title={t("sections.priceLists.title")}
      description={t("sections.priceLists.description")}
      actions={
        <Button
          onClick={() => {
            setCreating(true);
          }}
        >
          <Plus />
          {t("prices.addList")}
        </Button>
      }
    >
      <QueryState loading={lists.isPending} error={lists.error} onRetry={() => void lists.refetch()}>
        {lists.data?.length === 0 ? (
          <EmptyState icon={<Tags />} title={t("prices.emptyTitle")} description={t("prices.emptyDescription")} />
        ) : (
          <ul className="grid grid-cols-1 gap-3 md:grid-cols-2 2xl:grid-cols-3">
            {(lists.data ?? []).map((list) => (
              <li key={list.id}>
                <PriceListCard list={list} />
              </li>
            ))}
          </ul>
        )}
      </QueryState>
      {creating ? (
        <CreateListDialog
          onClose={() => {
            setCreating(false);
          }}
        />
      ) : null}
    </AdminPage>
  );
}

function PriceListCard({ list }: { list: PriceListOut }) {
  const { t } = useTranslation("admin");
  const localName = useLocalName();
  const current = list.versions.find((v) => v.id === list.current_version_id);
  const next = list.versions.find((v) => v.id === list.next_version_id);
  return (
    <Link
      to="/administration/price-lists/$priceListId"
      params={{ priceListId: String(list.id) }}
      className="card-surface group flex h-full flex-col gap-3 p-4 focus-ring transition-colors hover:border-primary/40 md:p-5"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate font-semibold text-fg">{localName(list)}</div>
          <Code>{list.code}</Code>
        </div>
        <ChevronNext className="mt-1 size-4 shrink-0 text-muted" />
      </div>
      <div className="flex flex-wrap gap-1">
        <Badge variant="outline">{t(`prices.kinds.${list.kind}`)}</Badge>
        {list.is_default ? <Badge variant="soft">{t("prices.default")}</Badge> : null}
        <ActiveBadge active={list.active} />
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
        <dt className="text-muted">{t("prices.currentFrom")}</dt>
        <dd className="text-end text-fg">{current ? <DateText value={current.effective_from} /> : "—"}</dd>
        <dt className="text-muted">{t("prices.nextFrom")}</dt>
        <dd className="text-end text-fg">
          {next ? (
            <span className="inline-flex items-center gap-1">
              <CalendarClock className="size-3.5 text-info" aria-hidden="true" />
              <DateText value={next.effective_from} />
            </span>
          ) : (
            "—"
          )}
        </dd>
        <dt className="text-muted">{t("prices.payers")}</dt>
        <dd className="min-w-0 truncate text-end text-fg">
          {list.payer_codes.length > 0 ? <Code>{list.payer_codes.join(", ")}</Code> : "—"}
        </dd>
      </dl>
    </Link>
  );
}

function CreateListDialog({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation("admin");
  const navigate = useNavigate();
  const create = useCreatePriceList();
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { code: "", name_ar: "", name_en: "", kind: "payer" },
  });
  return (
    <FormDialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={t("prices.addList")}
      description={t("prices.addListHint")}
      form={form}
      error={create.error}
      onSubmit={async (values) => {
        const list = await create.mutateAsync(values);
        toast.success(t("common.saved"));
        onClose();
        await navigate({ to: "/administration/price-lists/$priceListId", params: { priceListId: String(list.id) } });
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
        label={t("prices.kind")}
        options={[
          { value: "payer", label: t("prices.kinds.payer") },
          { value: "cash", label: t("prices.kinds.cash") },
        ]}
      />
    </FormDialog>
  );
}
