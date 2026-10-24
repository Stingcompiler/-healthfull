import { Link } from "@tanstack/react-router";
import type { ColumnDef } from "@tanstack/react-table";
import { Droplet, Tag } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { AlertCard } from "@/components/AlertCard";
import { DataTable } from "@/components/DataTable";
import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { SearchInput } from "@/components/SearchInput";
import { Button } from "@/components/ui/button";
import { useTranslateError } from "@/lib/api/translate-error";

import { PAGE_SIZE, useCollectAtWard, useCollection } from "../api";
import { useLabNames } from "../lib/use-lab-names";
import type { WorklistRow } from "../types";

/**
 * Sample collection outside the lab (a nurse holds `lab.collect_sample` but not the bench):
 * paid or authorized tests waiting for a sample. Collecting starts the test; the lab receives
 * the sample. After collecting, the label can be printed.
 */
export function CollectionPage() {
  const { t } = useTranslation(["lab", "errors"]);
  const translateError = useTranslateError();
  const names = useLabNames();
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const list = useCollection(q, page);
  const collect = useCollectAtWard();
  const [collected, setCollected] = useState<Record<number, number>>({});

  const onCollect = (row: WorklistRow) => {
    collect.mutate(row.line_id, {
      onSuccess: (result) => {
        const sampleId = result.sample?.id;
        if (sampleId !== undefined) setCollected((prev) => ({ ...prev, [row.line_id]: sampleId }));
        toast.success(t("collection.done", { test: names.test(row.test) }));
      },
      onError: (error) => {
        toast.error(translateError(error));
      },
    });
  };

  const rows = list.data?.items ?? [];
  const columns = useMemo<ColumnDef<WorklistRow>[]>(
    () => [
      {
        id: "test",
        header: t("worklist.columns.test"),
        meta: { label: t("worklist.columns.test"), className: "whitespace-normal" },
        cell: ({ row }) => (
          <span className="flex min-w-0 flex-col">
            <span className="font-medium">{names.test(row.original.test)}</span>
            <span className="text-xs text-muted">{t(`sampleType.${row.original.test.sample_type}`)}</span>
          </span>
        ),
      },
      {
        id: "patient",
        header: t("worklist.columns.patient"),
        meta: { label: t("worklist.columns.patient"), className: "whitespace-normal" },
        cell: ({ row }) => (
          <span className="flex min-w-0 flex-col">
            <span>{names.patient(row.original.patient)}</span>
            <bdi className="num text-xs text-muted">{row.original.patient.file_no}</bdi>
          </span>
        ),
      },
      {
        id: "ordered",
        header: t("worklist.ordered"),
        meta: { label: t("worklist.ordered") },
        cell: ({ row }) => <DateText value={row.original.ordered_at} format="datetime" />,
      },
      {
        id: "action",
        header: t("collection.action"),
        meta: { label: t("collection.action"), align: "end" },
        cell: ({ row }) => (
          <CollectAction
            row={row.original}
            sampleId={collected[row.original.line_id]}
            onCollect={onCollect}
            busy={collect.isPending}
          />
        ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps -- onCollect closes over the latest state
    [t, names, collected, collect.isPending],
  );

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader title={t("collection.title")} description={t("collection.description")} />
      <SearchInput
        label={t("worklist.search")}
        placeholder={t("worklist.searchPlaceholder")}
        onSearch={(v) => {
          setQ(v);
          setPage(1);
        }}
        className="sm:max-w-sm"
      />
      {list.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(list.error)}
        </AlertCard>
      ) : (
        <DataTable
          columns={columns}
          data={rows}
          loading={list.isPending}
          getRowId={(r) => String(r.line_id)}
          caption={t("collection.title")}
          serverPagination={{ page, pageSize: PAGE_SIZE, count: list.data?.count ?? 0, onPageChange: setPage }}
          minTableWidth={640}
          emptyState={
            <EmptyState
              bare
              size="compact"
              icon={<Droplet />}
              title={t("collection.empty")}
              description={t("worklist.emptyHint")}
            />
          }
          renderCard={(r) => (
            <div className="card-surface flex flex-col gap-2 p-4" data-testid="collection-row" data-line-id={r.line_id}>
              <span className="font-semibold">{names.test(r.test)}</span>
              <span className="text-sm">{names.patient(r.patient)}</span>
              <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
                <bdi className="num">{r.patient.file_no}</bdi>
                <span>{t(`sampleType.${r.test.sample_type}`)}</span>
                <DateText value={r.ordered_at} format="datetime" />
              </span>
              <div className="flex justify-end">
                <CollectAction row={r} sampleId={collected[r.line_id]} onCollect={onCollect} busy={collect.isPending} />
              </div>
            </div>
          )}
        />
      )}
      {Object.entries(collected).length > 0 ? (
        <section className="card-surface flex flex-col gap-2 p-4" aria-labelledby="collected-now">
          <h2 id="collected-now" className="text-sm font-semibold text-fg">
            {t("collection.collectedNow")}
          </h2>
          <ul className="flex flex-wrap gap-2">
            {Object.entries(collected).map(([lineId, sampleId]) => (
              <li key={lineId}>
                <Button asChild variant="outline" size="sm">
                  <Link to="/lab/samples/$sampleId/label" params={{ sampleId: String(sampleId) }}>
                    <Tag aria-hidden="true" />
                    {t("collection.printLabel")}
                  </Link>
                </Button>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

function CollectAction({
  row,
  sampleId,
  onCollect,
  busy,
}: {
  row: WorklistRow;
  sampleId: number | undefined;
  onCollect: (row: WorklistRow) => void;
  busy: boolean;
}) {
  const { t } = useTranslation("lab");
  const names = useLabNames();
  if (sampleId !== undefined) {
    return (
      <Button asChild variant="outline" size="sm">
        <Link to="/lab/samples/$sampleId/label" params={{ sampleId: String(sampleId) }}>
          <Tag aria-hidden="true" />
          {t("collection.printLabel")}
        </Link>
      </Button>
    );
  }
  return (
    <Button
      size="sm"
      disabled={busy}
      data-testid="collection-collect"
      aria-label={t("collection.collectFor", { test: names.test(row.test), patient: names.patient(row.patient) })}
      onClick={() => {
        onCollect(row);
      }}
    >
      <Droplet aria-hidden="true" />
      {t("collection.collect")}
    </Button>
  );
}
