import {
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type PaginationState,
  type Row,
  type RowData,
  type SortingState,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown, MoreHorizontal } from "lucide-react";
import { useId, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { EmptyState } from "@/components/EmptyState";
import { ChevronNext, ChevronPrev, ChevronsNext, ChevronsPrev } from "@/components/icons";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatNumber } from "@/lib/format";
import { useBreakpoint } from "@/lib/hooks/use-media-query";
import { useLanguage } from "@/lib/i18n-hooks";
import { cn } from "@/lib/utils";

declare module "@tanstack/react-table" {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars -- generic names must match the library's declaration
  interface ColumnMeta<TData extends RowData, TValue> {
    /** Plain-text label used for sort buttons and the default card layout. */
    label?: string;
    align?: "start" | "end" | "center";
    /** Extra classes for header and cells. */
    className?: string;
    /** Leave out of the default card layout. */
    hideInCard?: boolean;
  }
}

export interface DataTableRowAction {
  label: string;
  icon?: ReactNode;
  onSelect: () => void;
  destructive?: boolean;
  disabled?: boolean;
  /** Draw a separator before this item. */
  separated?: boolean;
}

export interface DataTableProps<TData> {
  columns: ColumnDef<TData>[];
  data: readonly TData[];
  getRowId?: (row: TData, index: number) => string;
  /** Accessible name of the table (visually hidden caption). */
  caption: string;
  loading?: boolean;
  /** Card renderer for phones (< md). Receives the row actions menu. */
  renderCard?: (row: TData, context: { actions: ReactNode; row: Row<TData> }) => ReactNode;
  rowActions?: (row: TData) => DataTableRowAction[];
  onRowClick?: (row: TData) => void;
  emptyState?: ReactNode;
  initialSorting?: SortingState;
  pageSize?: number;
  pageSizeOptions?: readonly number[];
  /** "auto" = table at >= md, cards below. */
  mode?: "auto" | "table" | "cards";
  className?: string;
}

const alignClass = { start: "text-start", end: "text-end", center: "text-center" } as const;

export function DataTable<TData>({
  columns,
  data,
  getRowId,
  caption,
  loading = false,
  renderCard,
  rowActions,
  onRowClick,
  emptyState,
  initialSorting = [],
  pageSize = 10,
  pageSizeOptions = [10, 25, 50],
  mode = "auto",
  className,
}: DataTableProps<TData>) {
  const { t } = useTranslation();
  const isWide = useBreakpoint("md");
  const showCards = mode === "cards" || (mode === "auto" && !isWide);

  const [sorting, setSorting] = useState<SortingState>(initialSorting);
  const [pagination, setPagination] = useState<PaginationState>({ pageIndex: 0, pageSize });

  // TanStack Table manages its own memoization; the React Compiler must not
  // memoize around it (react-hooks/incompatible-library).
  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data: data as TData[],
    columns,
    state: { sorting, pagination },
    onSortingChange: setSorting,
    onPaginationChange: setPagination,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    autoResetPageIndex: true,
    ...(getRowId ? { getRowId } : {}),
  });

  const rows = table.getRowModel().rows;
  const isEmpty = !loading && data.length === 0;
  const hasActions = Boolean(rowActions);

  const actionsFor = (row: Row<TData>): ReactNode =>
    rowActions ? <RowActionsMenu actions={rowActions(row.original)} /> : null;

  const empty = emptyState ?? (
    <EmptyState bare size="compact" title={t("table.noResultsTitle")} description={t("table.noResultsDescription")} />
  );

  return (
    <div data-slot="data-table" className={cn("flex min-w-0 flex-col gap-3", className)}>
      {showCards ? (
        <div
          data-slot="data-table-cards"
          aria-label={caption}
          role="list"
          aria-busy={loading || undefined}
          className="flex flex-col gap-3"
        >
          {loading ? (
            Array.from({ length: 3 }, (_, i) => (
              <div key={i} role="listitem" className="card-surface flex flex-col gap-3 p-4">
                <Skeleton className="h-4 w-2/3" />
                <Skeleton className="h-3 w-1/2" />
                <Skeleton className="h-3 w-1/3" />
              </div>
            ))
          ) : isEmpty ? (
            <div className="card-surface">{empty}</div>
          ) : (
            rows.map((row) => (
              <div key={row.id} role="listitem" className="min-w-0">
                {renderCard ? (
                  renderCard(row.original, { actions: actionsFor(row), row })
                ) : (
                  <DefaultCard row={row} actions={actionsFor(row)} />
                )}
              </div>
            ))
          )}
        </div>
      ) : (
        <div className="card-surface overflow-hidden p-0">
          <Table aria-busy={loading || undefined}>
            <TableCaption className="sr-only">{caption}</TableCaption>
            <TableHeader>
              {table.getHeaderGroups().map((group) => (
                <TableRow key={group.id} className="hover:bg-transparent">
                  {group.headers.map((header) => {
                    const meta = header.column.columnDef.meta;
                    const sorted = header.column.getIsSorted();
                    const canSort = header.column.getCanSort();
                    const label = meta?.label ?? header.column.id;
                    return (
                      <TableHead
                        key={header.id}
                        aria-sort={sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : undefined}
                        className={cn(alignClass[meta?.align ?? "start"], meta?.className)}
                      >
                        {header.isPlaceholder ? null : canSort ? (
                          <button
                            type="button"
                            onClick={header.column.getToggleSortingHandler()}
                            className={cn(
                              "-mx-1.5 inline-flex items-center gap-1 rounded-[6px] px-1.5 py-1 hover:bg-accent hover:text-fg focus-visible:ring-3 focus-visible:ring-ring/35 focus-visible:outline-none",
                              sorted && "text-fg",
                            )}
                            aria-label={t("table.sortBy", { column: label })}
                          >
                            {flexRender(header.column.columnDef.header, header.getContext())}
                            {sorted === "asc" ? (
                              <ArrowUp className="size-3.5" aria-hidden="true" />
                            ) : sorted === "desc" ? (
                              <ArrowDown className="size-3.5" aria-hidden="true" />
                            ) : (
                              <ArrowUpDown className="size-3.5 opacity-50" aria-hidden="true" />
                            )}
                          </button>
                        ) : (
                          flexRender(header.column.columnDef.header, header.getContext())
                        )}
                      </TableHead>
                    );
                  })}
                  {hasActions ? (
                    <TableHead className="w-12 text-end">
                      <span className="sr-only">{t("table.actions")}</span>
                    </TableHead>
                  ) : null}
                </TableRow>
              ))}
            </TableHeader>
            <TableBody>
              {loading ? (
                Array.from({ length: Math.min(pagination.pageSize, 5) }, (_, i) => (
                  <TableRow key={`skeleton-${String(i)}`} className="hover:bg-transparent">
                    {table.getVisibleLeafColumns().map((col) => (
                      <TableCell key={col.id}>
                        <Skeleton className="h-4 w-full max-w-36" />
                      </TableCell>
                    ))}
                    {hasActions ? <TableCell /> : null}
                  </TableRow>
                ))
              ) : isEmpty ? (
                <TableRow className="hover:bg-transparent">
                  <TableCell
                    colSpan={table.getVisibleLeafColumns().length + (hasActions ? 1 : 0)}
                    className="whitespace-normal"
                  >
                    {empty}
                  </TableCell>
                </TableRow>
              ) : (
                rows.map((row) => (
                  <TableRow
                    key={row.id}
                    data-clickable={onRowClick ? true : undefined}
                    onClick={
                      onRowClick
                        ? () => {
                            onRowClick(row.original);
                          }
                        : undefined
                    }
                    className={cn(onRowClick && "cursor-pointer")}
                  >
                    {row.getVisibleCells().map((cell) => {
                      const meta = cell.column.columnDef.meta;
                      return (
                        <TableCell key={cell.id} className={cn(alignClass[meta?.align ?? "start"], meta?.className)}>
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </TableCell>
                      );
                    })}
                    {hasActions ? (
                      <TableCell
                        className="text-end"
                        onClick={(e) => {
                          e.stopPropagation();
                        }}
                      >
                        {actionsFor(row)}
                      </TableCell>
                    ) : null}
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      )}

      {!loading && data.length > 0 ? (
        <Pagination
          pageIndex={pagination.pageIndex}
          pageSize={pagination.pageSize}
          total={table.getPrePaginationRowModel().rows.length}
          pageCount={table.getPageCount()}
          pageSizeOptions={pageSizeOptions}
          onPageChange={(index) => {
            table.setPageIndex(index);
          }}
          onPageSizeChange={(size) => {
            table.setPageSize(size);
          }}
        />
      ) : null}
    </div>
  );
}

function RowActionsMenu({ actions }: { actions: DataTableRowAction[] }) {
  const { t } = useTranslation();
  if (actions.length === 0) return null;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon-sm" aria-label={t("table.rowActions")}>
          <MoreHorizontal />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {actions.map((action) => (
          <div key={action.label}>
            {action.separated ? <DropdownMenuSeparator /> : null}
            <DropdownMenuItem
              variant={action.destructive ? "destructive" : "default"}
              disabled={action.disabled}
              onSelect={action.onSelect}
            >
              {action.icon}
              {action.label}
            </DropdownMenuItem>
          </div>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function DefaultCard<TData>({ row, actions }: { row: Row<TData>; actions: ReactNode }) {
  const cells = row.getVisibleCells().filter((cell) => !cell.column.columnDef.meta?.hideInCard);
  const [first, ...rest] = cells;
  return (
    <div className="card-surface flex flex-col gap-3 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 font-semibold text-fg">
          {first ? flexRender(first.column.columnDef.cell, first.getContext()) : null}
        </div>
        {actions}
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
        {rest.map((cell) => (
          <div key={cell.id} className="contents">
            <dt className="text-muted">{cell.column.columnDef.meta?.label ?? cell.column.id}</dt>
            <dd className="min-w-0 text-end text-fg">{flexRender(cell.column.columnDef.cell, cell.getContext())}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

interface PaginationProps {
  pageIndex: number;
  pageSize: number;
  total: number;
  pageCount: number;
  pageSizeOptions: readonly number[];
  onPageChange: (index: number) => void;
  onPageSizeChange: (size: number) => void;
}

function Pagination({
  pageIndex,
  pageSize,
  total,
  pageCount,
  pageSizeOptions,
  onPageChange,
  onPageSizeChange,
}: PaginationProps) {
  const { t } = useTranslation();
  const language = useLanguage();
  const pageSizeLabelId = useId();
  const n = (value: number) => formatNumber(value, language);
  const from = total === 0 ? 0 : pageIndex * pageSize + 1;
  const to = Math.min(total, (pageIndex + 1) * pageSize);
  const canPrev = pageIndex > 0;
  const canNext = pageIndex < pageCount - 1;
  return (
    <nav
      aria-label={t("table.pageOf", { page: n(pageIndex + 1), pages: n(Math.max(pageCount, 1)) })}
      className="flex flex-wrap items-center justify-between gap-3 text-sm text-muted"
    >
      <div className="tabular" aria-live="polite">
        {t("table.range", { from: n(from), to: n(to), total: n(total) })}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <div className="hidden items-center gap-2 sm:flex">
          <span id={pageSizeLabelId}>{t("table.rowsPerPage")}</span>
          <Select
            value={String(pageSize)}
            onValueChange={(v) => {
              onPageSizeChange(Number(v));
            }}
          >
            <SelectTrigger size="sm" className="w-20" aria-labelledby={pageSizeLabelId}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {pageSizeOptions.map((size) => (
                <SelectItem key={size} value={String(size)}>
                  {n(size)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <span className="px-1 tabular">
          {t("table.pageOf", { page: n(pageIndex + 1), pages: n(Math.max(pageCount, 1)) })}
        </span>
        <div className="flex items-center gap-1">
          <Button
            variant="outline"
            size="icon-sm"
            className="hidden sm:inline-flex"
            disabled={!canPrev}
            onClick={() => {
              onPageChange(0);
            }}
            aria-label={t("table.firstPage")}
          >
            <ChevronsPrev />
          </Button>
          <Button
            variant="outline"
            size="icon-sm"
            disabled={!canPrev}
            onClick={() => {
              onPageChange(pageIndex - 1);
            }}
            aria-label={t("table.previousPage")}
          >
            <ChevronPrev />
          </Button>
          <Button
            variant="outline"
            size="icon-sm"
            disabled={!canNext}
            onClick={() => {
              onPageChange(pageIndex + 1);
            }}
            aria-label={t("table.nextPage")}
          >
            <ChevronNext />
          </Button>
          <Button
            variant="outline"
            size="icon-sm"
            className="hidden sm:inline-flex"
            disabled={!canNext}
            onClick={() => {
              onPageChange(pageCount - 1);
            }}
            aria-label={t("table.lastPage")}
          >
            <ChevronsNext />
          </Button>
        </div>
      </div>
    </nav>
  );
}
