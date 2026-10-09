import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import type { ColumnDef } from "@tanstack/react-table";
import { FilePlus2, FileStack } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { Can } from "@/components/Can";
import { DataTable, DataTableOpenButton } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { MoneyText } from "@/components/MoneyText";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useTranslateError } from "@/lib/api/translate-error";

import { PAGE_SIZE, useClaimOptions, useClaims } from "../api";
import { ClaimStatusBadge } from "../components/ClaimBadges";
import { ClaimsNav } from "../components/ClaimsNav";
import { Period } from "../components/Period";
import { useClaimNames } from "../lib/names";
import type { ClaimsSearch } from "../lib/search";
import { CLAIM_STATUSES, type ClaimStatus, type ClaimSummary } from "../types";

const ALL = "all";

/** Claim batches by status and payer (FEATURES 11.3); a row opens the claim. */
export function ClaimListPage() {
  const { t } = useTranslation(["claims", "errors"]);
  const translateError = useTranslateError();
  const names = useClaimNames();
  const navigate = useNavigate();
  const search: ClaimsSearch = useSearch({ strict: false });
  const [status, setStatus] = useState<ClaimStatus | typeof ALL>(ALL);
  const [page, setPage] = useState(1);
  const options = useClaimOptions();
  const claims = useClaims({ payerId: search.payer, status: status === ALL ? undefined : status, page });

  const open = (row: ClaimSummary) => {
    void navigate({ to: "/claims/$claimId", params: { claimId: String(row.id) } });
  };

  const columns = useMemo<ColumnDef<ClaimSummary>[]>(
    () => [
      {
        id: "number",
        header: t("list.columns.number"),
        meta: { label: t("list.columns.number") },
        cell: ({ row }) => <bdi className="font-medium">{row.original.number}</bdi>,
      },
      {
        id: "payer",
        header: t("list.columns.payer"),
        meta: { label: t("list.columns.payer"), className: "whitespace-normal" },
        cell: ({ row }) => names.name(row.original.payer),
      },
      {
        id: "period",
        header: t("list.columns.period"),
        meta: { label: t("list.columns.period") },
        cell: ({ row }) => <Period start={row.original.period_start} end={row.original.period_end} />,
      },
      {
        id: "status",
        header: t("list.columns.status"),
        meta: { label: t("list.columns.status") },
        cell: ({ row }) => <ClaimStatusBadge status={row.original.status} />,
      },
      {
        id: "claimed",
        header: t("list.columns.claimed"),
        meta: { label: t("list.columns.claimed"), align: "end" },
        cell: ({ row }) => <MoneyText value={row.original.claimed_total} currency={false} />,
      },
      {
        id: "accepted",
        header: t("list.columns.accepted"),
        meta: { label: t("list.columns.accepted"), align: "end" },
        cell: ({ row }) => <MoneyText value={row.original.accepted_total} currency={false} />,
      },
      {
        id: "paid",
        header: t("list.columns.paid"),
        meta: { label: t("list.columns.paid"), align: "end" },
        cell: ({ row }) => <MoneyText value={row.original.paid_total} currency={false} />,
      },
      {
        id: "receivable",
        header: t("list.columns.receivable"),
        meta: { label: t("list.columns.receivable"), align: "end" },
        cell: ({ row }) => <MoneyText value={row.original.receivable} currency={false} className="font-semibold" />,
      },
    ],
    [t, names],
  );

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader
        title={t("list.title")}
        description={t("list.description")}
        icon={<FileStack />}
        actions={
          <Can permission="claims.manage">
            <Button asChild>
              <Link to="/claims/new" search={search.payer ? { payer: search.payer } : {}}>
                <FilePlus2 aria-hidden="true" />
                {t("receivables.build")}
              </Link>
            </Button>
          </Can>
        }
      />
      <ClaimsNav />
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <Tabs
          value={status}
          onValueChange={(v) => {
            setStatus(v as ClaimStatus | typeof ALL);
            setPage(1);
          }}
        >
          <TabsList aria-label={t("list.filter")} className="flex-wrap">
            <TabsTrigger value={ALL}>{t("list.all")}</TabsTrigger>
            {CLAIM_STATUSES.map((s) => (
              <TabsTrigger key={s} value={s}>
                {t(`status.${s}`)}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        <Select
          value={search.payer ? String(search.payer) : ALL}
          onValueChange={(v) => {
            setPage(1);
            void navigate({ to: "/claims/batches", search: v === ALL ? {} : { payer: Number(v) } });
          }}
        >
          <SelectTrigger className="h-11 w-full lg:w-72" aria-label={t("list.payerFilter")}>
            <SelectValue placeholder={t("list.allPayers")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>{t("list.allPayers")}</SelectItem>
            {(options.data?.payers ?? []).map((p) => (
              <SelectItem key={p.id} value={String(p.id)}>
                {names.name(p)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {claims.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(claims.error)}
        </AlertCard>
      ) : (
        <DataTable
          columns={columns}
          data={claims.data?.items ?? []}
          loading={claims.isPending}
          getRowId={(r) => String(r.id)}
          caption={t("list.title")}
          onRowClick={open}
          rowLabel={(r) => t("list.open", { number: r.number })}
          serverPagination={{ page, pageSize: PAGE_SIZE, count: claims.data?.count ?? 0, onPageChange: setPage }}
          minTableWidth={980}
          emptyState={<EmptyState bare size="compact" icon={<FileStack />} title={t("list.empty")} />}
          renderCard={(r, ctx) => (
            <div className="card-surface relative flex flex-col gap-2 p-4" data-testid="claim-row">
              <div className="flex items-start justify-between gap-2">
                {ctx.open ? (
                  <DataTableOpenButton onOpen={ctx.open} label={ctx.openLabel}>
                    <bdi className="font-semibold">{r.number}</bdi>
                  </DataTableOpenButton>
                ) : (
                  <bdi className="font-semibold">{r.number}</bdi>
                )}
                <ClaimStatusBadge status={r.status} />
              </div>
              <span className="text-sm">{names.name(r.payer)}</span>
              <span className="text-sm text-muted">
                <Period start={r.period_start} end={r.period_end} />
              </span>
              <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
                <div className="flex flex-col">
                  <dt className="text-xs text-muted">{t("list.columns.claimed")}</dt>
                  <dd>
                    <MoneyText value={r.claimed_total} currency={false} />
                  </dd>
                </div>
                <div className="flex flex-col">
                  <dt className="text-xs text-muted">{t("list.columns.receivable")}</dt>
                  <dd>
                    <MoneyText value={r.receivable} currency={false} className="font-semibold" />
                  </dd>
                </div>
              </dl>
            </div>
          )}
        />
      )}
    </div>
  );
}
