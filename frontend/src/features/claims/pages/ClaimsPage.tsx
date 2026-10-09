import { Link, useNavigate } from "@tanstack/react-router";
import type { ColumnDef } from "@tanstack/react-table";
import { CircleDollarSign, FilePlus2, FileStack, Hourglass, Scale, Undo2 } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { Can } from "@/components/Can";
import { DataTable, type DataTableRowAction } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { KpiCard } from "@/components/KpiCard";
import { MoneyText } from "@/components/MoneyText";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { useTranslateError } from "@/lib/api/translate-error";
import { usePermission } from "@/lib/auth/hooks";

import { useReceivables } from "../api";
import { ClaimsNav } from "../components/ClaimsNav";
import { useClaimNames } from "../lib/names";
import type { ClaimReceivable, ClaimStages } from "../types";

const STAGE_COLUMNS: readonly (keyof ClaimStages)[] = [
  "accrued",
  "claimed",
  "accepted_unpaid",
  "rejected_unresolved",
  "receivable",
  "collected",
];

/**
 * Payer receivables by stage (FEATURES 11.2, 12.7): what each payer owes, from accrued on an
 * approved invoice to collected by a payer payment. Payer share is never cash until a payer
 * payment is recorded (invariant 7), so only "collected" is money received.
 */
export function ClaimsPage() {
  const { t } = useTranslation(["claims", "errors"]);
  const translateError = useTranslateError();
  const names = useClaimNames();
  const navigate = useNavigate();
  const data = useReceivables();
  const canBuild = usePermission("claims.manage");
  const totals = data.data?.totals;

  const actions = (row: ClaimReceivable): DataTableRowAction[] => {
    const out: DataTableRowAction[] = [
      {
        label: t("receivables.viewClaims"),
        icon: <FileStack />,
        onSelect: () => {
          void navigate({ to: "/claims/batches", search: { payer: row.payer.id } });
        },
      },
    ];
    if (canBuild && row.stages.accrued !== "0.00")
      out.unshift({
        label: t("receivables.build"),
        icon: <FilePlus2 />,
        onSelect: () => {
          void navigate({ to: "/claims/new", search: { payer: row.payer.id } });
        },
      });
    return out;
  };

  const columns = useMemo<ColumnDef<ClaimReceivable>[]>(
    () => [
      {
        id: "payer",
        header: t("receivables.columns.payer"),
        meta: { label: t("receivables.columns.payer"), className: "whitespace-normal" },
        cell: ({ row }) => (
          <span className="flex min-w-0 flex-col">
            <span className="font-medium">{names.name(row.original.payer)}</span>
            <bdi className="text-xs text-muted">{row.original.payer.code}</bdi>
          </span>
        ),
      },
      ...STAGE_COLUMNS.map<ColumnDef<ClaimReceivable>>((key) => ({
        id: key,
        header: t(`stages.${key}`),
        meta: { label: t(`stages.${key}`), align: "end" },
        cell: ({ row }) => (
          <MoneyText
            value={row.original.stages[key]}
            currency={false}
            className={key === "receivable" ? "font-semibold" : undefined}
          />
        ),
      })),
    ],
    [t, names],
  );

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader
        title={t("receivables.title")}
        description={t("receivables.description")}
        icon={<Scale />}
        actions={
          <Can permission="claims.manage">
            <Button asChild>
              <Link to="/claims/new" data-testid="build-claim-link">
                <FilePlus2 aria-hidden="true" />
                {t("receivables.build")}
              </Link>
            </Button>
          </Can>
        }
      />
      <ClaimsNav />
      {data.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(data.error)}
        </AlertCard>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4" data-testid="receivable-kpis">
            <KpiCard
              label={t("stages.receivable")}
              value={totals ? <MoneyText value={totals.receivable} /> : null}
              hint={t("receivables.receivableHint")}
              icon={<Scale />}
              loading={data.isPending}
            />
            <KpiCard
              label={t("stages.accrued")}
              value={totals ? <MoneyText value={totals.accrued} /> : null}
              hint={t("receivables.accruedHint")}
              icon={<FilePlus2 />}
              tone="info"
              loading={data.isPending}
            />
            <KpiCard
              label={t("stages.claimed")}
              value={totals ? <MoneyText value={totals.claimed} /> : null}
              hint={t("receivables.claimedHint")}
              icon={<Hourglass />}
              tone="warning"
              loading={data.isPending}
            />
            <KpiCard
              label={t("stages.collected")}
              value={totals ? <MoneyText value={totals.collected} /> : null}
              hint={t("receivables.collectedHint")}
              icon={<CircleDollarSign />}
              tone="success"
              loading={data.isPending}
            />
          </div>
          {totals && totals.rejected_unresolved !== "0.00" ? (
            <AlertCard variant="warning" title={t("receivables.rejectedTitle")}>
              <span className="flex flex-wrap items-center gap-x-2">
                <MoneyText value={totals.rejected_unresolved} />
                <span>{t("receivables.rejectedBody")}</span>
              </span>
            </AlertCard>
          ) : null}
          <DataTable
            columns={columns}
            data={data.data?.items ?? []}
            loading={data.isPending}
            getRowId={(r) => String(r.payer.id)}
            caption={t("receivables.title")}
            rowActions={actions}
            minTableWidth={900}
            emptyState={<EmptyState bare size="compact" icon={<Scale />} title={t("receivables.empty")} />}
            renderCard={(r, ctx) => (
              <div className="card-surface flex flex-col gap-3 p-4" data-testid="receivable-row">
                <div className="flex items-start justify-between gap-2">
                  <span className="flex min-w-0 flex-col">
                    <span className="font-semibold">{names.name(r.payer)}</span>
                    <bdi className="text-xs text-muted">{r.payer.code}</bdi>
                  </span>
                  {ctx.actions}
                </div>
                <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
                  {STAGE_COLUMNS.map((key) => (
                    <div key={key} className="flex min-w-0 flex-col">
                      <dt className="text-xs text-muted">{t(`stages.${key}`)}</dt>
                      <dd>
                        <MoneyText
                          value={r.stages[key]}
                          currency={false}
                          className={key === "receivable" ? "font-semibold" : undefined}
                        />
                      </dd>
                    </div>
                  ))}
                </dl>
              </div>
            )}
          />
          {totals ? (
            <p className="flex flex-wrap items-center gap-x-2 text-sm text-muted">
              <Undo2 className="size-4 shrink-0" aria-hidden="true" />
              <span>{t("stages.rebilled")}:</span>
              <MoneyText value={totals.rebilled} />
              <span aria-hidden="true">·</span>
              <span>{t("stages.written_off")}:</span>
              <MoneyText value={totals.written_off} />
            </p>
          ) : null}
        </>
      )}
    </div>
  );
}
