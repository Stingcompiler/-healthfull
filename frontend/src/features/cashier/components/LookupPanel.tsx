import { Search } from "lucide-react";
import { useTranslation } from "react-i18next";

import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { ChevronNext } from "@/components/icons";
import { KbdCombo } from "@/components/Kbd";
import { MoneyText } from "@/components/MoneyText";
import { SearchInput } from "@/components/SearchInput";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

import { useLookup } from "../api";
import { useNames } from "../lib/use-names";
import type { LookupVisit } from "../types";

export const LOOKUP_INPUT_ID = "cashier-lookup";
export const LOOKUP_SHORTCUT = "f2";

/** Find a patient by file number, visit number, phone or name, then pick the visit to bill. */
export function LookupPanel({
  query,
  onQueryChange,
  selectedVisitId,
  onSelectVisit,
}: {
  query: string;
  onQueryChange: (q: string) => void;
  selectedVisitId: number | undefined;
  onSelectVisit: (visitId: number) => void;
}) {
  const { t } = useTranslation("cashier");
  const names = useNames();
  const lookup = useLookup(query);
  const items = lookup.data?.items ?? [];
  const onlyVisit = items.length === 1 && items[0]?.visits.length === 1 ? items[0].visits[0] : undefined;

  return (
    <section aria-labelledby="lookup-title" className="card-surface flex min-w-0 flex-col gap-3 p-4 md:p-5">
      <div className="flex items-center justify-between gap-2">
        <h2 id="lookup-title" className="text-base font-semibold">
          {t("lookup.title")}
        </h2>
        <KbdCombo combo={LOOKUP_SHORTCUT} className="hidden md:inline-flex" />
      </div>
      <SearchInput
        id={LOOKUP_INPUT_ID}
        label={t("lookup.label")}
        placeholder={t("lookup.placeholder")}
        defaultValue={query}
        onSearch={onQueryChange}
        loading={lookup.isFetching}
        autoComplete="off"
        onKeyDown={(e) => {
          if (e.key === "Enter" && onlyVisit) {
            e.preventDefault();
            onSelectVisit(onlyVisit.id);
          }
        }}
        data-testid="cashier-lookup"
      />
      {query.trim() === "" ? (
        <p className="text-sm text-muted">{t("lookup.hint")}</p>
      ) : lookup.isPending ? (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          bare
          size="compact"
          icon={<Search />}
          title={t("lookup.noResults")}
          description={t("lookup.noResultsHint")}
        />
      ) : (
        <ul className="flex flex-col gap-3" data-testid="lookup-results">
          {items.map((item) => (
            <li key={item.patient.id} className="flex min-w-0 flex-col gap-2 rounded-control border border-border p-3">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="min-w-0 font-medium break-words">{names.patient(item.patient)}</span>
                <bdi className="tabular text-sm text-muted">{item.patient.file_no}</bdi>
              </div>
              {item.balance.outstanding !== "0.00" || item.balance.credit !== "0.00" ? (
                <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
                  {item.balance.outstanding !== "0.00" ? (
                    <span>
                      {t("lookup.outstanding")} <MoneyText value={item.balance.outstanding} />
                    </span>
                  ) : null}
                  {item.balance.credit !== "0.00" ? (
                    <span>
                      {t("lookup.credit")} <MoneyText value={item.balance.credit} />
                    </span>
                  ) : null}
                </div>
              ) : null}
              {item.visits.length === 0 ? (
                <p className="text-sm text-muted">{t("lookup.noVisits")}</p>
              ) : (
                <ul className="flex flex-col gap-1.5">
                  {item.visits.map((v) => (
                    <li key={v.id}>
                      <VisitButton
                        visit={v}
                        selected={v.id === selectedVisitId}
                        onSelect={() => {
                          onSelectVisit(v.id);
                        }}
                      />
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function VisitButton({ visit, selected, onSelect }: { visit: LookupVisit; selected: boolean; onSelect: () => void }) {
  const { t } = useTranslation("cashier");
  const names = useNames();
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      data-testid="lookup-visit"
      data-visit-number={visit.number}
      className={cn(
        "flex w-full min-w-0 items-center gap-2 rounded-control border px-3 py-2 text-start focus-ring",
        selected ? "border-primary bg-primary-soft" : "border-border bg-surface hover:bg-accent",
      )}
    >
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="flex flex-wrap items-center gap-2 text-sm font-medium">
          <bdi>{visit.number}</bdi>
          {visit.department ? <span className="text-muted">{names.name(visit.department)}</span> : null}
        </span>
        <span className="flex flex-wrap items-center gap-1.5 text-xs text-muted">
          <DateText value={visit.created_at} format="datetime" />
          {visit.payer ? <Badge variant="info">{names.name(visit.payer)}</Badge> : null}
          {visit.unbilled_count > 0 ? (
            <Badge variant="warning">{t("lookup.unbilled", { count: visit.unbilled_count })}</Badge>
          ) : null}
          {visit.outstanding !== "0.00" ? (
            <Badge variant="danger">
              <MoneyText value={visit.outstanding} />
            </Badge>
          ) : null}
        </span>
      </span>
      <ChevronNext className="size-4 shrink-0 text-muted" aria-hidden="true" />
    </button>
  );
}
