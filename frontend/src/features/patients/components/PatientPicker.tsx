import { Check, UserRound } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { SearchInput } from "@/components/SearchInput";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useLanguage } from "@/lib/i18n-hooks";
import { cn } from "@/lib/utils";

import { usePatientList } from "../api";
import { patientName } from "../lib";
import type { PatientListItem } from "../types";

export interface PatientPickerProps {
  value: PatientListItem | null;
  onChange: (patient: PatientListItem | null) => void;
  /** Files that cannot be picked (e.g. the file being merged into). */
  excludeIds?: readonly number[];
  label?: string;
  autoFocus?: boolean;
  /** Show the picked file without the "change" action. */
  readOnly?: boolean;
}

/**
 * Find a patient file by name, phone or file number (FEATURES 0.9) and pick it. Shows the picked
 * file with a "change" action; the search list is a list of real buttons (keyboard operable).
 */
export function PatientPicker({
  value,
  onChange,
  excludeIds = [],
  label,
  autoFocus,
  readOnly = false,
}: PatientPickerProps) {
  const { t } = useTranslation("patients");
  const language = useLanguage();
  const [term, setTerm] = useState("");
  const query = usePatientList({ q: term, page: 1, pageSize: 8 }, term.trim().length >= 2);
  const rows = (query.data?.items ?? []).filter((p) => !excludeIds.includes(p.id));

  if (value) {
    return (
      <div
        data-testid="picked-patient"
        className="flex min-w-0 items-center gap-3 rounded-control border border-border bg-subtle p-3"
      >
        <UserRound className="size-5 shrink-0 text-muted" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <p className="font-semibold break-words text-fg">{patientName(value, language)}</p>
          <p className="text-xs text-muted">
            <bdi className="tabular">{value.file_no}</bdi>
            {value.phone ? (
              <>
                {" · "}
                <bdi className="tabular">{value.phone}</bdi>
              </>
            ) : null}
          </p>
        </div>
        {readOnly ? null : (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              onChange(null);
            }}
          >
            {t("picker.change")}
          </Button>
        )}
      </div>
    );
  }

  return (
    <div className="grid gap-2">
      <SearchInput
        label={label ?? t("picker.label")}
        placeholder={t("picker.placeholder")}
        onSearch={setTerm}
        loading={query.isFetching}
        autoFocus={autoFocus}
      />
      {term.trim().length >= 2 ? (
        rows.length > 0 ? (
          <ul aria-label={t("picker.results")} className="grid max-h-64 gap-1 overflow-y-auto">
            {rows.map((p) => (
              <li key={p.id}>
                <button
                  type="button"
                  onClick={() => {
                    onChange(p);
                  }}
                  className={cn(
                    "flex w-full min-w-0 items-center gap-3 rounded-control border border-border px-3 py-2 text-start focus-ring",
                    "hover:bg-accent hover:text-accent-fg",
                  )}
                >
                  <Check className="size-4 shrink-0 text-transparent" aria-hidden="true" />
                  <span className="min-w-0 flex-1">
                    <span className="block font-medium break-words">{patientName(p, language)}</span>
                    <span className="block text-xs text-muted">
                      <bdi className="tabular">{p.file_no}</bdi>
                      {p.phone ? (
                        <>
                          {" · "}
                          <bdi className="tabular">{p.phone}</bdi>
                        </>
                      ) : null}
                    </span>
                  </span>
                  {p.is_incomplete ? <Badge variant="warning">{t("badges.incomplete")}</Badge> : null}
                </button>
              </li>
            ))}
          </ul>
        ) : query.isFetching ? null : (
          <p className="text-sm text-muted">{t("picker.noResults")}</p>
        )
      ) : (
        <p className="text-sm text-muted">{t("picker.hint")}</p>
      )}
    </div>
  );
}
