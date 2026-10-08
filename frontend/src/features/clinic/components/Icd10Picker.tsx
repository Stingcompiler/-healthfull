import { Check, X } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { SearchInput } from "@/components/SearchInput";
import { Button } from "@/components/ui/button";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";
import { cn } from "@/lib/utils";

import { useIcd10Search } from "../api";
import type { Icd10 } from "../types";
import { useCombobox } from "../use-combobox";

/**
 * ICD-10 lookup by code prefix or words of the title (Arabic or English), as a combobox:
 * ArrowUp/ArrowDown pick a row, Enter takes the highlighted one (never a row left from the
 * previous query).
 */
export function Icd10Picker({
  value,
  onChange,
  label,
}: {
  value: Icd10 | null;
  onChange: (code: Icd10 | null) => void;
  label: string;
}) {
  const { t } = useTranslation("clinic");
  const language = useLanguage();
  const [query, setQuery] = useState("");
  const [term, setTerm] = useState("");
  const search = useIcd10Search(term);
  const results = term.length >= 2 ? (search.data ?? []) : [];

  const pick = (code: Icd10) => {
    onChange(code);
    setQuery("");
    setTerm("");
  };

  const box = useCombobox({
    query,
    term,
    search: setTerm,
    results,
    settled: search.isSuccess && !search.isPlaceholderData && !search.isFetching,
    onPick: pick,
  });

  return (
    <div className="flex min-w-0 flex-col gap-2">
      <SearchInput
        label={label}
        placeholder={t("diagnosis.searchPlaceholder")}
        value={query}
        onValueChange={setQuery}
        onSearch={setTerm}
        delayMs={200}
        loading={search.isFetching}
        data-testid="icd10-search"
        data-fresh={box.fresh ? "true" : "false"}
        {...box.inputProps}
      />
      <p className="sr-only" aria-live="polite">
        {term.length >= 2 && box.fresh ? t("diagnosis.resultCount", { count: results.length }) : ""}
      </p>
      {value ? (
        <div className="flex min-w-0 items-center gap-2 rounded-control border border-primary bg-primary-soft py-1 ps-3 pe-1 text-sm text-primary-strong">
          <Check className="size-4 shrink-0" aria-hidden="true" />
          <bdi className="tabular font-semibold">{value.code}</bdi>
          <span className="min-w-0 truncate">{pickName({ ar: value.title_ar, en: value.title_en }, language)}</span>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="ms-auto shrink-0"
            onClick={() => {
              onChange(null);
            }}
            aria-label={t("diagnosis.clearCodeNamed", { code: value.code })}
          >
            <X aria-hidden="true" />
            {t("diagnosis.clearCode")}
          </Button>
        </div>
      ) : null}
      {results.length > 0 ? (
        <ul
          {...box.listProps}
          className="flex max-h-60 flex-col overflow-y-auto rounded-control border border-border"
          aria-label={t("diagnosis.results")}
          data-testid="icd10-results"
        >
          {results.map((code, index) => {
            const highlighted = box.fresh && index === box.active;
            return (
              <li
                key={code.code}
                {...box.optionProps(index)}
                onClick={() => {
                  pick(code);
                }}
                className={cn(
                  "flex min-h-11 w-full min-w-0 cursor-pointer items-baseline gap-2 border-b border-border px-3 py-2.5 text-start text-sm last:border-b-0 hover:bg-accent md:min-h-0 md:py-2",
                  value?.code === code.code && "bg-primary-soft",
                  highlighted && "bg-accent",
                )}
                data-highlighted={highlighted ? "true" : undefined}
              >
                <bdi className="w-14 shrink-0 tabular font-semibold">{code.code}</bdi>
                <span className="min-w-0 break-words">
                  {pickName({ ar: code.title_ar, en: code.title_en }, language)}
                </span>
              </li>
            );
          })}
        </ul>
      ) : term.length >= 2 && search.isSuccess && !search.isFetching ? (
        <p className="text-xs text-muted">{t("diagnosis.noMatch")}</p>
      ) : null}
    </div>
  );
}
