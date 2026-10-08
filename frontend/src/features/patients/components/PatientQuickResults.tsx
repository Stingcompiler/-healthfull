import { useNavigate } from "@tanstack/react-router";
import { Loader2, UserRound } from "lucide-react";
import { useTranslation } from "react-i18next";

import { CommandGroup, CommandItem } from "@/components/ui/command";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";
import { useLanguage } from "@/lib/i18n-hooks";

import { usePatientList } from "../api";
import { patientName } from "../lib";

/** Shortest typed text that searches patient files (one letter matches too much). */
const MIN_QUERY = 2;
const LIMIT = 8;

/** The quick search's patient results (see `usePatientQuickSearch`). */
export function PatientQuickResults({ query, onDone }: { query: string; onDone: () => void }) {
  const { t } = useTranslation("patients");
  const language = useLanguage();
  const navigate = useNavigate();
  const term = useDebouncedValue(query.trim(), 250);
  const enabled = term.length >= MIN_QUERY;
  const found = usePatientList({ q: term, page: 1, pageSize: LIMIT }, enabled);
  if (!enabled) return null;
  const items = found.data?.items ?? [];
  return (
    <CommandGroup heading={t("quickSearch.group")} forceMount>
      {found.isFetching && items.length === 0 ? (
        <CommandItem disabled forceMount value={`patients-loading ${query}`}>
          <Loader2 className="animate-spin" aria-hidden="true" />
          <span>{t("quickSearch.searching")}</span>
        </CommandItem>
      ) : null}
      {found.isError ? (
        <CommandItem disabled forceMount value={`patients-error ${query}`}>
          <span className="text-danger">{t("quickSearch.failed")}</span>
        </CommandItem>
      ) : null}
      {items.map((p) => (
        <CommandItem
          key={p.id}
          forceMount
          value={`patient-${String(p.id)} ${p.file_no} ${p.full_name_ar} ${p.full_name_en} ${query}`}
          onSelect={() => {
            onDone();
            void navigate({ to: "/patients/$patientId", params: { patientId: String(p.id) } });
          }}
          data-testid="quick-search-patient"
        >
          <UserRound aria-hidden="true" />
          <span className="flex min-w-0 flex-1 flex-col">
            <span className="break-words">{patientName(p, language)}</span>
            <span className="text-xs text-muted">
              <bdi className="tabular">{p.file_no}</bdi>
              {p.phone ? (
                <>
                  {" · "}
                  <bdi className="tabular">{p.phone}</bdi>
                </>
              ) : null}
            </span>
          </span>
        </CommandItem>
      ))}
      {found.isSuccess && found.data.count > items.length ? (
        <CommandItem
          forceMount
          value={`patients-more ${query}`}
          onSelect={() => {
            onDone();
            void navigate({ to: "/patients", search: { q: term } });
          }}
        >
          <span className="text-primary">{t("quickSearch.more", { count: found.data.count })}</span>
        </CommandItem>
      ) : null}
    </CommandGroup>
  );
}
