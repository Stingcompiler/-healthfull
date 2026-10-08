import { Plus } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Kbd } from "@/components/Kbd";
import { SearchInput } from "@/components/SearchInput";
import { Button } from "@/components/ui/button";
import { useShortcut } from "@/lib/hooks/use-shortcut";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";
import { cn } from "@/lib/utils";

import { useCatalog } from "../api";
import type { OrderableKind, OrderableService } from "../types";
import { KIND_ICONS } from "../kind-icons";

const SEARCH_ID = "catalog-search-input";
const KINDS: readonly (OrderableKind | null)[] = [null, "lab", "procedure", "drug", "consumable"];

/** Search the orderable catalog (no prices); Enter adds the first match, "/" focuses the search. */
export function CatalogPicker({ onPick }: { onPick: (service: OrderableService) => void }) {
  const { t } = useTranslation("clinic");
  const language = useLanguage();
  const [query, setQuery] = useState("");
  const [term, setTerm] = useState("");
  const [kind, setKind] = useState<OrderableKind | null>(null);
  const catalog = useCatalog(term, kind);
  const results = term ? (catalog.data ?? []) : [];
  const focusSearch = () => document.getElementById(SEARCH_ID)?.focus();

  useShortcut("/", focusSearch);

  const pick = (service: OrderableService) => {
    onPick(service);
    setQuery("");
    setTerm("");
    focusSearch();
  };

  return (
    <div className="flex min-w-0 flex-col gap-2" data-testid="catalog-picker">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-fg">{t("orders.catalog")}</h3>
        <span className="text-xs text-muted max-md:hidden">
          {t("orders.searchHint")} <Kbd>/</Kbd>
        </span>
      </div>
      <div className="flex flex-wrap gap-1.5" role="group" aria-label={t("orders.kindFilter")}>
        {KINDS.map((k) => (
          <Button
            key={k ?? "all"}
            size="sm"
            variant={kind === k ? "soft" : "ghost"}
            aria-pressed={kind === k}
            onClick={() => setKind(k)}
          >
            {k ? t(`kind.${k}`) : t("orders.allKinds")}
          </Button>
        ))}
      </div>
      <SearchInput
        id={SEARCH_ID}
        label={t("orders.searchLabel")}
        placeholder={t("orders.searchPlaceholder")}
        value={query}
        onValueChange={setQuery}
        onSearch={setTerm}
        delayMs={200}
        loading={catalog.isFetching}
        data-testid="catalog-search"
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            const first = results[0];
            if (first) pick(first);
          }
        }}
      />
      {results.length > 0 ? (
        <ul
          className="flex max-h-72 flex-col overflow-y-auto rounded-control border border-border"
          data-testid="catalog-results"
        >
          {results.map((service) => {
            const Icon = KIND_ICONS[service.kind];
            return (
              <li key={service.id} className="border-b border-border last:border-b-0">
                <button
                  type="button"
                  onClick={() => pick(service)}
                  className="flex w-full min-w-0 items-center gap-2 px-3 py-2 text-start text-sm focus-ring-inset hover:bg-accent"
                  data-service-code={service.code}
                >
                  <Icon className="size-4 shrink-0 text-muted" aria-hidden="true" />
                  <span className="min-w-0 flex-1">
                    <span className="block break-words text-fg">
                      {pickName({ ar: service.name_ar, en: service.name_en }, language)}
                    </span>
                    <span className="block text-xs text-muted">
                      <bdi>{service.code}</bdi>
                      {service.drug
                        ? ` · ${[service.drug.generic_name, service.drug.strength].filter(Boolean).join(" ")}`
                        : ""}
                    </span>
                  </span>
                  <Plus className={cn("size-4 shrink-0 text-primary-strong")} aria-hidden="true" />
                </button>
              </li>
            );
          })}
        </ul>
      ) : term && catalog.isSuccess && !catalog.isFetching ? (
        <p className="text-xs text-muted">{t("orders.noMatch")}</p>
      ) : null}
    </div>
  );
}
