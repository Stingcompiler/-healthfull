import type { ColumnDef } from "@tanstack/react-table";
import { Inbox } from "lucide-react";
import { useMemo, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { DataTable } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

import type { ReportRow, ReportSection } from "../types";
import { isNumeric, sortValue } from "../lib/cells";
import { ReportCell } from "./ReportCell";

/** Width each report column needs before the table switches to cards. */
const COLUMN_WIDTH = 132;

/**
 * One section of a report: a table on wide screens, cards on phones (DataTable), with the
 * section's totals row under the columns.
 */
export function ReportSectionTable({
  section,
  maxRows,
  loading = false,
}: {
  section: ReportSection;
  maxRows: number;
  loading?: boolean;
}) {
  const { t } = useTranslation("reports");
  const language = useLanguage();
  const title = pickName(section.label, language);

  const columns = useMemo<ColumnDef<ReportRow>[]>(
    () =>
      section.columns.map((column) => {
        const label = pickName(column.label, language);
        const numeric = isNumeric(column.kind);
        return {
          id: column.key,
          header: label,
          accessorFn: (row) => sortValue(row[column.key], column.kind, language),
          sortUndefined: "last",
          meta: {
            label,
            align: numeric ? "end" : "start",
            className: column.kind === "name" || column.kind === "text" ? "whitespace-normal" : undefined,
          },
          cell: ({ row }) => <ReportCell value={row.original[column.key]} kind={column.kind} />,
        } satisfies ColumnDef<ReportRow>;
      }),
    [section.columns, language],
  );

  const totals = useMemo(() => {
    if (!section.totals) return undefined;
    const cells: Record<string, ReactNode> = {};
    for (const column of section.columns) {
      const value = section.totals[column.key];
      if (value === undefined) continue;
      cells[column.key] = <ReportCell value={value} kind={column.kind} />;
    }
    return { cells, label: t("viewer.total") };
  }, [section.totals, section.columns, t]);

  return (
    <section
      className="flex min-w-0 flex-col gap-3"
      aria-labelledby={`section-${section.key}`}
      data-testid={`section-${section.key}`}
    >
      <h2 id={`section-${section.key}`} className="text-base font-semibold text-fg">
        {title}
      </h2>
      {section.truncated ? (
        <AlertCard variant="warning" title={t("viewer.truncatedTitle")}>
          {t("viewer.truncated", { rows: maxRows })}
        </AlertCard>
      ) : null}
      <DataTable
        columns={columns}
        data={section.rows}
        caption={title}
        loading={loading}
        totals={totals}
        pageSize={25}
        pageSizeOptions={[25, 50, 100]}
        minTableWidth={Math.max(560, section.columns.length * COLUMN_WIDTH)}
        emptyState={
          <EmptyState
            bare
            size="compact"
            icon={<Inbox />}
            title={t("viewer.emptyTitle")}
            description={t("viewer.emptyDescription")}
          />
        }
      />
    </section>
  );
}
