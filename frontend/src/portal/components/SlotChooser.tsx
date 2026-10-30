import { type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";
import { formatDate } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";
import { cn } from "@/lib/utils";

import { useBookingDays, useDoctors, useSlots } from "../api";
import { formatDay, usePick } from "../lib/ui";
import { PortalSection } from "./PortalPage";

/** A selectable option shown as a large button (radio semantics). */
export function Choice({
  selected,
  onSelect,
  children,
  testId,
  className,
}: {
  selected: boolean;
  onSelect: () => void;
  children: ReactNode;
  testId: string;
  className?: string;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onSelect}
      data-testid={testId}
      className={cn(
        "min-h-11 rounded-control border px-3 py-2 text-sm focus-ring",
        selected
          ? "border-primary bg-primary-soft font-semibold text-primary-strong"
          : "border-border-strong bg-surface text-fg hover:bg-accent",
        className,
      )}
    >
      {children}
    </button>
  );
}

export interface SlotChoice {
  doctorId: number | null;
  day: string | null;
  start: string | null;
}

/**
 * Doctor, then day, then a free time (public reads, ADR 0029 Phase 4a: patients and guests
 * see the same free times). Controlled: the parent keeps the choice; choosing a doctor clears
 * the day and time, choosing a day clears the time.
 */
export function SlotChooser({ value, onChange }: { value: SlotChoice; onChange: (next: SlotChoice) => void }) {
  const { t } = useTranslation(["portal", "errors"]);
  const translateError = useTranslateError();
  const pick = usePick();
  const language = useLanguage();
  const { doctorId, day, start } = value;
  const doctors = useDoctors();
  const days = useBookingDays(doctorId);
  const slots = useSlots(doctorId, day);

  return (
    <>
      <PortalSection title={t("book.doctor")}>
        {doctors.isPending ? (
          <Skeleton className="h-24" />
        ) : doctors.isError ? (
          <AlertCard variant="danger" title={translateError(doctors.error)} />
        ) : doctors.data.length === 0 ? (
          <p className="text-sm text-muted">{t("book.noDoctors")}</p>
        ) : (
          <div role="radiogroup" aria-label={t("book.doctor")} className="grid gap-2 md:grid-cols-2">
            {doctors.data.map((d) => (
              <Choice
                key={d.id}
                selected={d.id === doctorId}
                testId="book-doctor"
                className="flex flex-col items-start text-start"
                onSelect={() => {
                  onChange({ doctorId: d.id, day: null, start: null });
                }}
              >
                <span className="font-semibold">{pick(d.name_ar, d.name_en)}</span>
                <span className="text-xs font-normal text-muted">
                  {[pick(d.specialty_ar, d.specialty_en), pick(d.department_ar, d.department_en)]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </Choice>
            ))}
          </div>
        )}
      </PortalSection>

      <PortalSection title={t("book.day")}>
        {doctorId === null ? (
          <p className="text-sm text-muted">{t("book.chooseDoctorFirst")}</p>
        ) : days.isPending ? (
          <Skeleton className="h-20" />
        ) : days.isError ? (
          <AlertCard variant="danger" title={translateError(days.error)} />
        ) : days.data.length === 0 ? (
          <p className="text-sm text-muted">{t("book.noDays")}</p>
        ) : (
          <div
            role="radiogroup"
            aria-label={t("book.day")}
            className="grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-5"
          >
            {days.data.map((d) => (
              <Choice
                key={d}
                selected={d === day}
                testId="book-day"
                onSelect={() => {
                  onChange({ doctorId, day: d, start: null });
                }}
              >
                <bdi>{formatDay(d, language)}</bdi>
              </Choice>
            ))}
          </div>
        )}
      </PortalSection>

      <PortalSection title={t("book.time")}>
        {day === null ? (
          <p className="text-sm text-muted">{t("book.chooseDayFirst")}</p>
        ) : slots.isPending ? (
          <Skeleton className="h-20" />
        ) : slots.isError ? (
          <AlertCard variant="danger" title={translateError(slots.error)} />
        ) : slots.data.slots.length === 0 ? (
          <p className="text-sm text-muted">{t("book.noSlots")}</p>
        ) : (
          <div role="radiogroup" aria-label={t("book.time")} className="grid grid-cols-3 gap-2 sm:grid-cols-4">
            {slots.data.slots.map((s) => (
              <Choice
                key={s.starts_at}
                selected={s.starts_at === start}
                testId="book-slot"
                onSelect={() => {
                  onChange({ doctorId, day, start: s.starts_at });
                }}
              >
                <bdi className="tabular">{formatDate(s.starts_at, language, "time")}</bdi>
              </Choice>
            ))}
          </div>
        )}
      </PortalSection>
    </>
  );
}
