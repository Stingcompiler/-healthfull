import { X } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { DateText } from "@/components/DateText";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";

import { useItems, useStoreBatches } from "../api";
import { useNames } from "../lib/use-names";
import type { StockItemListItem, StoreBatch } from "../types";
import { LabeledField, QtyText } from "./common";

/**
 * A search box with its results listed under it (inline, so it works inside dialogs and on
 * phones). The chosen row shows in place of the box until cleared.
 */
function SearchPick<T>({
  label,
  placeholder,
  results,
  loading,
  rowKey,
  renderRow,
  selected,
  onPick,
  onClear,
  onQuery,
  testId,
  required,
  error,
}: {
  label: string;
  placeholder: string;
  results: readonly T[];
  loading: boolean;
  rowKey: (row: T) => string;
  renderRow: (row: T) => ReactNode;
  selected: ReactNode;
  onPick: (row: T) => void;
  onClear: () => void;
  onQuery: (q: string) => void;
  testId: string;
  required?: boolean;
  error?: string | null;
}) {
  const { t } = useTranslation("pharmacy");
  const [q, setQ] = useState("");
  return (
    <LabeledField label={label} required={required} error={error}>
      {(id, describedBy) =>
        selected ? (
          <div className="flex min-h-11 items-center justify-between gap-2 rounded-control border border-border-strong bg-subtle px-3 py-1.5 text-sm md:min-h-10">
            <span className="min-w-0 break-words" data-testid={`${testId}-selected`}>
              {selected}
            </span>
            <Button type="button" variant="ghost" size="icon-sm" onClick={onClear} aria-label={t("common.change")}>
              <X aria-hidden="true" />
            </Button>
          </div>
        ) : (
          <div className="grid gap-1">
            <Input
              id={id}
              type="search"
              value={q}
              autoComplete="off"
              placeholder={placeholder}
              aria-describedby={describedBy}
              aria-invalid={error ? true : undefined}
              data-testid={testId}
              onChange={(e) => {
                setQ(e.target.value);
                onQuery(e.target.value);
              }}
            />
            {q.trim() ? (
              <ul
                className="grid max-h-56 overflow-y-auto rounded-control border border-border bg-surface"
                aria-label={label}
                data-testid={`${testId}-results`}
              >
                {loading && results.length === 0 ? (
                  <li className="px-3 py-2 text-sm text-muted">{t("common.searching")}</li>
                ) : results.length === 0 ? (
                  <li className="px-3 py-2 text-sm text-muted">{t("common.noResults")}</li>
                ) : (
                  results.map((row) => (
                    <li key={rowKey(row)}>
                      <button
                        type="button"
                        className="w-full px-3 py-2 text-start text-sm focus-ring hover:bg-accent"
                        onClick={() => {
                          setQ("");
                          onPick(row);
                        }}
                      >
                        {renderRow(row)}
                      </button>
                    </li>
                  ))
                )}
              </ul>
            ) : null}
          </div>
        )
      }
    </LabeledField>
  );
}

function itemLabel(item: { generic_name: string; strength: string; brand_name?: string }): string {
  return [item.generic_name, item.strength].filter(Boolean).join(" ");
}

/** Find a stock item by name, brand, code or barcode. */
export function ItemPicker({
  label,
  value,
  onChange,
  testId,
  error,
}: {
  label: string;
  value: StockItemListItem | null;
  onChange: (item: StockItemListItem | null) => void;
  testId: string;
  error?: string | null;
}) {
  const { t } = useTranslation("pharmacy");
  const [q, setQ] = useState("");
  const debounced = useDebouncedValue(q, 250);
  const items = useItems(debounced, false, 1);
  return (
    <SearchPick
      label={label}
      placeholder={t("pickers.itemPlaceholder")}
      results={debounced.trim() ? (items.data?.items ?? []) : []}
      loading={items.isFetching}
      rowKey={(it) => String(it.id)}
      renderRow={(it) => (
        <span className="flex flex-col">
          <span className="font-medium">{itemLabel(it)}</span>
          <span className="text-xs text-muted">
            <bdi>{it.service.code}</bdi>
            {it.brand_name ? ` · ${it.brand_name}` : ""}
          </span>
        </span>
      )}
      selected={value ? itemLabel(value) : null}
      onPick={onChange}
      onClear={() => {
        onChange(null);
      }}
      onQuery={setQ}
      testId={testId}
      required
      error={error}
    />
  );
}

/** Find a batch with stock in a store by item name, batch number or barcode. */
export function BatchPicker({
  label,
  storeId,
  value,
  onChange,
  testId,
  error,
}: {
  label: string;
  storeId: number | undefined;
  value: StoreBatch | null;
  onChange: (batch: StoreBatch | null) => void;
  testId: string;
  error?: string | null;
}) {
  const { t } = useTranslation("pharmacy");
  const names = useNames();
  const [q, setQ] = useState("");
  const debounced = useDebouncedValue(q, 250);
  const batches = useStoreBatches(storeId, debounced);
  return (
    <SearchPick
      label={label}
      placeholder={storeId === undefined ? t("pickers.storeFirst") : t("pickers.batchPlaceholder")}
      results={debounced.trim() ? (batches.data ?? []) : []}
      loading={batches.isFetching}
      rowKey={(b) => `${String(b.batch_id)}-${String(b.store_id)}`}
      renderRow={(b) => (
        <span className="flex flex-col">
          <span className="font-medium">{b.item_name}</span>
          <span className="flex flex-wrap gap-x-2 text-xs text-muted">
            <bdi>{b.batch_no}</bdi>
            <DateText value={b.expiry_date} />
            <QtyText value={b.on_hand} unit={names.baseUnit(b)} />
          </span>
        </span>
      )}
      selected={
        value ? (
          <span className="flex flex-wrap gap-x-2">
            <span className="font-medium">{value.item_name}</span>
            <bdi>{value.batch_no}</bdi>
            <QtyText value={value.on_hand} unit={names.baseUnit(value)} className="text-muted" />
          </span>
        ) : null
      }
      onPick={onChange}
      onClear={() => {
        onChange(null);
      }}
      onQuery={setQ}
      testId={testId}
      required
      error={error}
    />
  );
}
