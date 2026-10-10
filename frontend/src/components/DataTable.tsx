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
import { useId, useRef, useState, type ReactNode } from "react";
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
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatNumber } from "@/lib/format";
import { useElementWidth } from "@/lib/hooks/use-element-width";
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

export interface DataTableCardContext<TData> {
  /** The row actions menu (or null). Keep it above the open overlay: it already is. */
  actions: ReactNode;
  row: Row<TData>;
  /**
   * Opens the row (calls onRowClick); undefined without onRowClick. Wrap the card title in
   * `<DataTableOpenButton onOpen={open} label=...>` so the whole card opens by click, touch
   * and keyboard.
   */
  open?: () => void;
  /** Accessible name for opening this row (from rowLabel). */
  openLabel?: string;
}

export interface DataTableProps<TData> {
  columns: ColumnDef<TData>[];
  data: readonly TData[];
  getRowId?: (row: TData, index: number) => string;
  /** Accessible name of the table (visually hidden caption). */
  caption: string;
  loading?: boolean;
  /** Card renderer for the card list. Receives the row actions menu and the open callback. */
  renderCard?: (row: TData, context: DataTableCardContext<TData>) => ReactNode;
  rowActions?: (row: TData) => DataTableRowAction[];
  /**
   * Opens a row (details page). The first column becomes a real button (keyboard and screen
   * reader operable) stretched over the row or card, so keep that column's cell free of other
   * interactive elements.
   */
  onRowClick?: (row: TData) => void;
  /** Accessible name of the open button, e.g. row => `Open ${row.name}`. Default: cell text. */
  rowLabel?: (row: TData) => string;
  emptyState?: ReactNode;
  initialSorting?: SortingState;
  pageSize?: number;
  pageSizeOptions?: readonly number[];
  /**
   * "auto" = cards below the md viewport breakpoint AND whenever the space actually available
   * to the table (its container) is narrower than `minTableWidth`, e.g. beside the tablet rail.
   */
  mode?: "auto" | "table" | "cards";
  /** Narrowest container width (px) that shows the table in auto mode. Default from columns. */
  minTableWidth?: number;
  /**
   * The parent pages on the server (`{items, count, page, page_size}`): `data` is page `page`
   * (1-based) of `count` rows. The pager shows the true total and asks for other pages through
   * `onPageChange`; there is no rows-per-page choice.
   */
  serverPagination?: ServerPagination;
  /**
   * A totals row over every row (not only the page): cell content by column id, under the
   * table's columns (a `<tfoot>`), or as a closing card in the card list. The first column
   * shows `label` (default "Total") unless `totals` fills it.
   */
  totals?: DataTableTotals;
  className?: string;
}

export interface DataTableTotals {
  cells: Partial<Record<string, ReactNode>>;
  label?: string;
}

export interface ServerPagination {
  page: number;
  pageSize: number;
  count: number;
  onPageChange: (page: number) => void;
}

const alignClass = { start: "text-start", end: "text-end", center: "text-center" } as const;

/** Rough width each column needs before the table stops fitting (auto mode default). */
const COLUMN_MIN_WIDTH = 112;
const ACTIONS_COLUMN_WIDTH = 56;

/**
 * The open control of a row or card: a real button whose ::after covers the nearest
 * positioned ancestor (the row/card), so a click anywhere opens it while keyboard and
 * screen reader users get one named control.
 */
export function DataTableOpenButton({
  onOpen,
  label,
  children,
  className,
}: {
  onOpen: () => void;
  label?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-label={label}
      data-slot="data-table-open"
      className={cn(
        "min-w-0 cursor-pointer rounded-[4px] text-start",
        "focus-ring-inset after:absolute after:inset-0 after:content-[''] focus-visible:after:rounded-[inherit]",
        className,
      )}
    >
      {children}
    </button>
  );
}

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
  minTableWidth,
  rowLabel,
  serverPagination,
  totals,
  className,
}: DataTableProps<TData>) {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement>(null);
  const isWide = useBreakpoint("md");
  const containerWidth = useElementWidth(containerRef);
  const neededWidth = minTableWidth ?? columns.length * COLUMN_MIN_WIDTH + (rowActions ? ACTIONS_COLUMN_WIDTH : 0);
  const tableFits = isWide && (containerWidth === null || containerWidth >= neededWidth);
  const showCards = mode === "cards" || (mode === "auto" && !tableFits);

  const [sorting, setSorting] = useState<SortingState>(initialSorting);
  const [localPagination, setPagination] = useState<PaginationState>({ pageIndex: 0, pageSize });
  const server = serverPagination;
  const pagination: PaginationState = server
    ? { pageIndex: Math.max(server.page - 1, 0), pageSize: server.pageSize }
    : localPagination;
  const serverPageCount = server ? Math.max(1, Math.ceil(server.count / server.pageSize)) : undefined;

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
    manualPagination: Boolean(server),
    autoResetPageIndex: !server,
    ...(serverPageCount !== undefined ? { pageCount: serverPageCount } : {}),
    ...(getRowId ? { getRowId } : {}),
  });

  const rows = table.getRowModel().rows;
  const isEmpty = !loading && data.length === 0;
  const hasActions = Boolean(rowActions);

  const actionsFor = (row: Row<TData>): ReactNode =>
    rowActions ? <RowActionsMenu actions={rowActions(row.original)} /> : null;
  const openFor = (row: Row<TData>): (() => void) | undefined =>
    onRowClick
      ? () => {
          onRowClick(row.original);
        }
      : undefined;

  const empty = emptyState ?? (
    <EmptyState bare size="compact" title={t("table.noResultsTitle")} description={t("table.noResultsDescription")} />
  );

  return (
    <div
      ref={containerRef}
      data-slot="data-table"
      data-mode={showCards ? "cards" : "table"}
      className={cn("flex min-w-0 flex-col gap-3", className)}
    >
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
            rows.map((row) => {
              const open = openFor(row);
              const openLabel = rowLabel?.(row.original);
              return (
                // relative: the open button's overlay covers exactly this card.
                <div key={row.id} role="listitem" className="relative min-w-0">
                  {renderCard ? (
                    renderCard(row.original, { actions: actionsFor(row), row, open, openLabel })
                  ) : (
                    <DefaultCard row={row} actions={actionsFor(row)} open={open} openLabel={openLabel} />
                  )}
                </div>
              );
            })
          )}
          {totals && !loading && !isEmpty ? (
            <div
              role="listitem"
              data-slot="data-table-totals"
              className="card-surface flex flex-col gap-3 bg-subtle p-4"
            >
              <div className="font-semibold text-fg">{totals.label ?? t("table.total")}</div>
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
                {table
                  .getVisibleLeafColumns()
                  .filter((col) => totals.cells[col.id] !== undefined && !col.columnDef.meta?.hideInCard)
                  .map((col) => (
                    <div key={col.id} className="contents">
                      <dt className="text-muted">{col.columnDef.meta?.label ?? col.id}</dt>
                      <dd className="min-w-0 text-end font-semibold text-fg">{totals.cells[col.id]}</dd>
                    </div>
                  ))}
              </dl>
            </div>
          ) : null}
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
                              "-mx-1.5 inline-flex items-center gap-1 rounded-[6px] px-1.5 py-1 focus-ring-inset hover:bg-accent hover:text-fg",
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
                    // Sticky at the inline end: row actions stay reachable when the table scrolls.
                    <TableHead className="sticky end-0 z-[1] w-12 bg-subtle text-end">
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
                rows.map((row) => {
                  const open = openFor(row);
                  return (
                    <TableRow
                      key={row.id}
                      data-clickable={open ? true : undefined}
                      // Mouse convenience only; the first cell holds the real (keyboard) control.
                      onClick={open}
                      className={cn(open && "cursor-pointer")}
                    >
                      {row.getVisibleCells().map((cell, index) => {
                        const meta = cell.column.columnDef.meta;
                        const content = flexRender(cell.column.columnDef.cell, cell.getContext());
                        return (
                          <TableCell key={cell.id} className={cn(alignClass[meta?.align ?? "start"], meta?.className)}>
                            {open && index === 0 ? (
                              <button
                                type="button"
                                data-slot="data-table-open"
                                aria-label={rowLabel?.(row.original)}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  open();
                                }}
                                className="cursor-pointer rounded-[4px] text-start font-medium text-fg underline-offset-4 focus-ring hover:underline"
                              >
                                {content}
                              </button>
                            ) : (
                              content
                            )}
                          </TableCell>
                        );
                      })}
                      {hasActions ? (
                        <TableCell
                          className="sticky end-0 z-[1] bg-surface text-end"
                          onClick={(e) => {
                            e.stopPropagation();
                          }}
                        >
                          {actionsFor(row)}
                        </TableCell>
                      ) : null}
                    </TableRow>
                  );
                })
              )}
            </TableBody>
            {totals && !loading && !isEmpty ? (
              <TableFooter data-slot="data-table-totals">
                <TableRow className="hover:bg-transparent">
                  {table.getVisibleLeafColumns().map((col, index) => {
                    const meta = col.columnDef.meta;
                    const content = totals.cells[col.id] ?? (index === 0 ? (totals.label ?? t("table.total")) : null);
                    return (
                      <TableCell
                        key={col.id}
                        className={cn("font-semibold", alignClass[meta?.align ?? "start"], meta?.className)}
                      >
                        {content}
                      </TableCell>
                    );
                  })}
                  {hasActions ? <TableCell /> : null}
                </TableRow>
              </TableFooter>
            ) : null}
          </Table>
        </div>
      )}

      {!loading && data.length > 0 ? (
        <Pagination
          pageIndex={pagination.pageIndex}
          pageSize={pagination.pageSize}
          total={server ? server.count : table.getPrePaginationRowModel().rows.length}
          pageCount={serverPageCount ?? table.getPageCount()}
          pageSizeOptions={server ? [server.pageSize] : pageSizeOptions}
          onPageChange={(index) => {
            if (server) server.onPageChange(index + 1);
            else table.setPageIndex(index);
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

function DefaultCard<TData>({
  row,
  actions,
  open,
  openLabel,
}: {
  row: Row<TData>;
  actions: ReactNode;
  open?: () => void;
  openLabel?: string;
}) {
  const cells = row.getVisibleCells().filter((cell) => !cell.column.columnDef.meta?.hideInCard);
  const [first, ...rest] = cells;
  const title = first ? flexRender(first.column.columnDef.cell, first.getContext()) : null;
  return (
    <div className={cn("card-surface flex flex-col gap-3 p-4", open && "transition-colors hover:border-primary/40")}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 font-semibold text-fg">
          {open ? (
            <DataTableOpenButton onOpen={open} label={openLabel}>
              {title}
            </DataTableOpenButton>
          ) : (
            title
          )}
        </div>
        {/* Above the open overlay so the menu stays clickable. */}
        {actions ? <div className="relative z-[1] shrink-0">{actions}</div> : null}
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
        {/* One option is no choice: the select is left out (e.g. server-side pages). */}
        {pageSizeOptions.length > 1 ? (
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
        ) : null}
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
