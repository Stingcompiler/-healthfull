import { Loader2, Search, X } from "lucide-react";
import { useEffect, useRef, useState, type ComponentProps } from "react";
import { useTranslation } from "react-i18next";

import { Input } from "@/components/ui/input";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";
import { cn } from "@/lib/utils";

export interface SearchInputProps extends Omit<
  ComponentProps<typeof Input>,
  "value" | "defaultValue" | "onChange" | "type"
> {
  /** Controlled value (optional). */
  value?: string;
  defaultValue?: string;
  /** Every keystroke. */
  onValueChange?: (value: string) => void;
  /** Debounced; fires after the user pauses typing. */
  onSearch?: (value: string) => void;
  delayMs?: number;
  /** Show a spinner while results load. */
  loading?: boolean;
  /** Accessible label when there is no visible one. */
  label: string;
}

export function SearchInput({
  value: valueProp,
  defaultValue = "",
  onValueChange,
  onSearch,
  delayMs = 300,
  loading = false,
  label,
  className,
  placeholder,
  ...props
}: SearchInputProps) {
  const { t } = useTranslation();
  const [internal, setInternal] = useState(defaultValue);
  const value = valueProp ?? internal;
  const debounced = useDebouncedValue(value, delayMs);
  const inputRef = useRef<HTMLInputElement>(null);
  const lastSearched = useRef(debounced);
  const onSearchRef = useRef(onSearch);
  useEffect(() => {
    onSearchRef.current = onSearch;
  });

  useEffect(() => {
    if (debounced === lastSearched.current) return;
    lastSearched.current = debounced;
    onSearchRef.current?.(debounced.trim());
  }, [debounced]);

  const change = (next: string) => {
    setInternal(next);
    onValueChange?.(next);
  };

  return (
    <div data-slot="search-input" className={cn("relative w-full min-w-0", className)}>
      <Search
        className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-muted"
        aria-hidden="true"
      />
      <Input
        ref={inputRef}
        type="search"
        role="searchbox"
        aria-label={label}
        placeholder={placeholder ?? t("search.placeholder")}
        value={value}
        onChange={(e) => {
          change(e.target.value);
        }}
        onKeyDown={(e) => {
          if (e.key === "Escape" && value) {
            e.preventDefault();
            change("");
          }
        }}
        className="ps-9 pe-9 [&::-webkit-search-cancel-button]:hidden"
        {...props}
      />
      <div className="absolute inset-y-0 end-0 flex items-center pe-1.5">
        {loading ? (
          <Loader2 className="me-1.5 size-4 animate-spin text-muted" aria-label={t("a11y.loading")} />
        ) : value ? (
          <button
            type="button"
            onClick={() => {
              change("");
              inputRef.current?.focus();
            }}
            className="inline-flex size-7 items-center justify-center rounded-[6px] text-muted hover:bg-accent hover:text-fg focus-visible:ring-3 focus-visible:ring-ring/35 focus-visible:outline-none"
          >
            <X className="size-4" aria-hidden="true" />
            <span className="sr-only">{t("search.clear")}</span>
          </button>
        ) : null}
      </div>
    </div>
  );
}
