import { Check } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { SearchInput } from "@/components/SearchInput";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";
import { cn } from "@/lib/utils";

import { useIcd10Search } from "../api";
import type { Icd10 } from "../types";

/**
 * ICD-10 lookup by code prefix or words of the title (Arabic or English). Enter picks the first
 * match; results are buttons, so Tab and Enter reach every one.
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
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            const first = results[0];
            if (first) pick(first);
          }
        }}
      />
      {value ? (
        <div className="flex min-w-0 items-center gap-2 rounded-control border border-primary bg-primary-soft px-3 py-2 text-sm text-primary-strong">
          <Check className="size-4 shrink-0" aria-hidden="true" />
          <bdi className="tabular font-semibold">{value.code}</bdi>
          <span className="min-w-0 truncate">{pickName({ ar: value.title_ar, en: value.title_en }, language)}</span>
          <button
            type="button"
            className="ms-auto shrink-0 text-xs underline focus-ring"
            onClick={() => {
              onChange(null);
            }}
          >
            {t("diagnosis.clearCode")}
          </button>
        </div>
      ) : null}
      {results.length > 0 ? (
        <ul
          className="flex max-h-60 flex-col overflow-y-auto rounded-control border border-border"
          aria-label={t("diagnosis.results")}
          data-testid="icd10-results"
        >
          {results.map((code) => (
            <li key={code.code} className="border-b border-border last:border-b-0">
              <button
                type="button"
                onClick={() => {
                  pick(code);
                }}
                className={cn(
                  "flex w-full min-w-0 items-baseline gap-2 px-3 py-2 text-start text-sm focus-ring-inset hover:bg-accent",
                  value?.code === code.code && "bg-primary-soft",
                )}
              >
                <bdi className="w-14 shrink-0 tabular font-semibold">{code.code}</bdi>
                <span className="min-w-0 break-words">
                  {pickName({ ar: code.title_ar, en: code.title_en }, language)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : term.length >= 2 && search.isSuccess && !search.isFetching ? (
        <p className="text-xs text-muted">{t("diagnosis.noMatch")}</p>
      ) : null}
    </div>
  );
}
