import { Plus, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Kbd } from "@/components/Kbd";
import { SearchInput } from "@/components/SearchInput";
import { Button } from "@/components/ui/button";
import { useShortcut } from "@/lib/hooks/use-shortcut";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";
import { cn } from "@/lib/utils";

import { useAllergyAlerts, useCatalog } from "../api";
import { KIND_ICONS } from "../kind-icons";
import type { OrderableKind, OrderableService } from "../types";
import { useCombobox } from "../use-combobox";

const SEARCH_ID = "catalog-search-input";
const KINDS: readonly (OrderableKind | null)[] = [null, "lab", "procedure", "drug", "consumable"];

/**
 * Search the orderable catalog (no prices) as a combobox: ArrowUp/ArrowDown pick a row, Enter
 * adds the highlighted one (never a row left from the previous query), "/" focuses the search.
 */
export function CatalogPicker({
  onPick,
  active = true,
  patientId,
}: {
  onPick: (service: OrderableService) => void;
  /** Whether the picker is on screen ("/" focuses it only then). */
  active?: boolean;
  /** Marks drug results that match one of this patient's allergies. */
  patientId?: number;
}) {
  const { t } = useTranslation("clinic");
  const language = useLanguage();
  const [query, setQuery] = useState("");
  const [term, setTerm] = useState("");
  const [kind, setKind] = useState<OrderableKind | null>(null);
  const catalog = useCatalog(term, kind);
  const results = term ? (catalog.data ?? []) : [];
  const drugIds = results
    .filter((r) => r.kind === "drug")
    .map((r) => r.id)
    .sort((a, b) => a - b);
  const alerts = useAllergyAlerts(patientId, drugIds);
  const allergic = new Set((alerts.data ?? []).map((a) => a.service_id));
  const focusSearch = () => document.getElementById(SEARCH_ID)?.focus();

  useShortcut("/", focusSearch, { enabled: active });

  const pick = (service: OrderableService) => {
    onPick(service);
    setQuery("");
    setTerm("");
    focusSearch();
  };

  const box = useCombobox({
    query,
    term,
    search: setTerm,
    results,
    settled: catalog.isSuccess && !catalog.isPlaceholderData && !catalog.isFetching,
    onPick: pick,
    onEscape: () => {
      setQuery("");
      setTerm("");
    },
    resetKey: `${term}|${kind ?? ""}`,
  });

  return (
    <div className="flex min-w-0 flex-col gap-2" data-testid="catalog-picker">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-fg">{t("orders.catalog")}</h3>
        <span className="text-xs text-muted max-md:hidden">
          {t("orders.searchHint")} <Kbd>/</Kbd>
        </span>
      </div>
      {/* One row on phones (scrolls sideways inside itself), wrapping from sm. */}
      <div
        className="-mx-1 flex scrollbar-thin flex-nowrap gap-1.5 overflow-x-auto px-1 pb-1 sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-0 sm:pb-0"
        role="group"
        aria-label={t("orders.kindFilter")}
      >
        {KINDS.map((k) => (
          <Button
            key={k ?? "all"}
            size="sm"
            variant={kind === k ? "soft" : "ghost"}
            aria-pressed={kind === k}
            className="shrink-0"
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
        data-fresh={box.fresh ? "true" : "false"}
        {...box.inputProps}
      />
      <p className="sr-only" aria-live="polite">
        {term && box.fresh ? t("orders.resultCount", { count: results.length }) : ""}
      </p>
      {results.length > 0 ? (
        <ul
          {...box.listProps}
          aria-label={t("orders.results")}
          className="flex max-h-72 flex-col overflow-y-auto rounded-control border border-border"
          data-testid="catalog-results"
        >
          {results.map((service, index) => {
            const Icon = KIND_ICONS[service.kind];
            const highlighted = box.fresh && index === box.active;
            const matchesAllergy = allergic.has(service.id);
            return (
              <li
                key={service.id}
                {...box.optionProps(index)}
                onClick={() => pick(service)}
                className={cn(
                  "flex min-h-11 w-full min-w-0 cursor-pointer items-center gap-2 border-b border-border px-3 py-2 text-start text-sm last:border-b-0 hover:bg-accent md:min-h-0",
                  highlighted && "bg-accent",
                )}
                data-service-code={service.code}
                data-highlighted={highlighted ? "true" : undefined}
                data-allergy={matchesAllergy ? "true" : undefined}
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
                {matchesAllergy ? (
                  <span className="inline-flex shrink-0 items-center gap-1 text-xs font-semibold text-danger-fg">
                    <ShieldAlert className="size-3.5" aria-hidden="true" />
                    {t("orders.allergyFlag")}
                  </span>
                ) : null}
                <Plus className="size-4 shrink-0 text-primary-strong" aria-hidden="true" />
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
