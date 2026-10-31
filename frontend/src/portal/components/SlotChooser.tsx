import { Check } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { ChevronNext, ChevronPrev } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";
import { formatDate } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";
import { initialsOf } from "@/lib/initials";
import { cn } from "@/lib/utils";

import { useBookingDays, useDoctors, useSlots } from "../api";
import { revealed } from "../guest/steps";
import { dayParts, useDoctorDetail, usePick } from "../lib/ui";

export interface SlotChoice {
  doctorId: number | null;
  day: string | null;
  start: string | null;
}

/** The website's chip: a rounded option with radio semantics (days and times). */
function Chip({
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
        "site-lift min-h-11 rounded-control border px-3 py-2 text-sm focus-ring",
        selected
          ? "border-primary bg-primary text-primary-fg shadow-card"
          : "border-border bg-surface text-fg hover:border-border-strong",
        className,
      )}
    >
      {children}
    </button>
  );
}

function PartTitle({ id, index, children }: { id: string; index: number; children: ReactNode }) {
  return (
    <h2 id={id} className="flex items-center gap-2 text-base font-semibold text-fg">
      <span className="num text-sm font-semibold text-primary-strong" aria-hidden="true">
        {index}.
      </span>
      {children}
    </h2>
  );
}

type RevealTarget = "day" | "time";

/** Brings a part that just appeared into view (it may be below the fold on a phone). */
function scrollIntoReach(node: HTMLElement | null) {
  if (!node || typeof node.scrollIntoView !== "function") return;
  const calm = typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  node.scrollIntoView({ behavior: calm ? "auto" : "smooth", block: "nearest" });
}

/**
 * The slot chooser of every booking screen (guest booking D-0023; the signed-in booking and
 * reschedule D-0024): doctors as selectable cards, the free days as a row of chips once a doctor
 * is chosen, the free times as a grid of chips once a day is. Nothing is shown for a part that
 * cannot be chosen yet. Public reads (ADR 0029 Phase 4a: patients and guests see the same free
 * times). Controlled: the parent keeps the choice; choosing another doctor clears the day and
 * time, choosing a day clears the time.
 */
export function SiteSlotChooser({ value, onChange }: { value: SlotChoice; onChange: (next: SlotChoice) => void }) {
  const { t } = useTranslation(["portal", "errors"]);
  const translateError = useTranslateError();
  const pick = usePick();
  const detail = useDoctorDetail();
  const language = useLanguage();
  const { doctorId, day, start } = value;
  const doctors = useDoctors();
  const days = useBookingDays(doctorId);
  const slots = useSlots(doctorId, day);
  const show = revealed(value);
  const dayRef = useRef<HTMLElement | null>(null);
  const timeRef = useRef<HTMLElement | null>(null);
  // Each choice the visitor makes brings the next part into reach (not on the first render).
  const [reveal, setReveal] = useState<{ target: RevealTarget; n: number } | null>(null);
  const next = (target: RevealTarget) => {
    setReveal((r) => ({ target, n: (r?.n ?? 0) + 1 }));
  };
  const dayRow = useRef<HTMLDivElement | null>(null);
  /** Pages the day row by most of its width, toward later (1) or earlier (-1) days in reading order. */
  const pageDays = (direction: 1 | -1) => {
    const row = dayRow.current;
    if (!row) return;
    const rtl = getComputedStyle(row).direction === "rtl";
    const calm =
      typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    row.scrollBy({ left: direction * (rtl ? -1 : 1) * row.clientWidth * 0.8, behavior: calm ? "auto" : "smooth" });
  };
  useEffect(() => {
    if (reveal) scrollIntoReach(reveal.target === "day" ? dayRef.current : timeRef.current);
  }, [reveal]);

  return (
    <div className="flex min-w-0 flex-col gap-6" data-testid="slot-chooser">
      <section aria-labelledby="slot-doctor" className="flex min-w-0 flex-col gap-3">
        <PartTitle id="slot-doctor" index={1}>
          {t("book.doctor")}
        </PartTitle>
        {doctors.isPending ? (
          <Skeleton className="h-24" />
        ) : doctors.isError ? (
          <AlertCard variant="danger" title={translateError(doctors.error)} />
        ) : doctors.data.length === 0 ? (
          <p className="text-sm text-muted">{t("book.noDoctors")}</p>
        ) : (
          <div role="radiogroup" aria-labelledby="slot-doctor" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {doctors.data.map((d) => {
              const selected = d.id === doctorId;
              const name = pick(d.name_ar, d.name_en);
              const sub = detail(d);
              return (
                <button
                  key={d.id}
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  data-testid="book-doctor"
                  onClick={() => {
                    // Choosing the chosen doctor again keeps the day and time.
                    if (selected) return;
                    onChange({ doctorId: d.id, day: null, start: null });
                    next("day");
                  }}
                  className={cn(
                    "site-lift flex min-h-16 min-w-0 items-center gap-3 rounded-[calc(var(--card-radius)+0.25rem)] border p-3 text-start focus-ring",
                    selected
                      ? "border-primary bg-primary-soft text-fg"
                      : "border-border bg-surface text-fg hover:border-border-strong",
                  )}
                >
                  <span
                    aria-hidden="true"
                    className={cn(
                      "inline-flex size-10 shrink-0 items-center justify-center rounded-full border text-sm font-semibold",
                      selected
                        ? "border-primary bg-primary text-primary-fg"
                        : "border-border bg-surface text-primary-strong",
                    )}
                  >
                    {selected ? <Check className="size-5" /> : initialsOf(name) || "·"}
                  </span>
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span className="text-sm font-semibold break-words">{name}</span>
                    {sub ? <span className="text-xs text-muted">{sub}</span> : null}
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </section>

      {show.day ? (
        <section
          ref={dayRef}
          aria-labelledby="slot-day"
          className="flex min-w-0 scroll-mt-20 scroll-mb-32 flex-col gap-3 border-t border-border pt-5"
        >
          <div className="flex items-center justify-between gap-2">
            <PartTitle id="slot-day" index={2}>
              {t("book.day")}
            </PartTitle>
            {days.data && days.data.length > 0 ? (
              // Mouse users page the row; touch swipes it and the keyboard tabs through it.
              <div className="flex gap-1 max-md:hidden">
                <Button
                  variant="outline"
                  size="icon-sm"
                  aria-label={t("book.earlierDays")}
                  title={t("book.earlierDays")}
                  onClick={() => {
                    pageDays(-1);
                  }}
                >
                  <ChevronPrev className="size-4" />
                </Button>
                <Button
                  variant="outline"
                  size="icon-sm"
                  aria-label={t("book.laterDays")}
                  title={t("book.laterDays")}
                  onClick={() => {
                    pageDays(1);
                  }}
                >
                  <ChevronNext className="size-4" />
                </Button>
              </div>
            ) : null}
          </div>
          {days.isPending ? (
            <Skeleton className="h-16" />
          ) : days.isError ? (
            <AlertCard variant="danger" title={translateError(days.error)} />
          ) : days.data.length === 0 ? (
            <p className="text-sm text-muted">{t("book.noDays")}</p>
          ) : (
            <div
              role="radiogroup"
              aria-labelledby="slot-day"
              ref={dayRow}
              // One swipeable row at every width: the next weeks stay one line, not a calendar wall.
              className="-mx-1 flex snap-x scroll-px-1 gap-2 overflow-x-auto px-1 pt-0.5 pb-2"
            >
              {days.data.map((d) => {
                const parts = dayParts(d, language);
                return (
                  <Chip
                    key={d}
                    selected={d === day}
                    testId="book-day"
                    className="flex min-w-[4.75rem] shrink-0 snap-start flex-col items-center gap-0.5 px-2.5"
                    onSelect={() => {
                      onChange({ doctorId, day: d, start: null });
                      next("time");
                    }}
                  >
                    <span className="text-xs">{parts.weekday}</span>
                    <bdi className="font-semibold whitespace-nowrap">{parts.date}</bdi>
                  </Chip>
                );
              })}
            </div>
          )}
        </section>
      ) : null}

      {show.time ? (
        <section
          ref={timeRef}
          aria-labelledby="slot-time"
          className="flex min-w-0 scroll-mt-20 scroll-mb-32 flex-col gap-3 border-t border-border pt-5"
        >
          <PartTitle id="slot-time" index={3}>
            {t("book.time")}
          </PartTitle>
          {slots.isPending ? (
            <Skeleton className="h-16" />
          ) : slots.isError ? (
            <AlertCard variant="danger" title={translateError(slots.error)} />
          ) : slots.data.slots.length === 0 ? (
            <p className="text-sm text-muted">{t("book.noSlots")}</p>
          ) : (
            <div
              role="radiogroup"
              aria-labelledby="slot-time"
              className="grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-5 xl:grid-cols-6"
            >
              {slots.data.slots.map((s) => (
                <Chip
                  key={s.starts_at}
                  selected={s.starts_at === start}
                  testId="book-slot"
                  onSelect={() => {
                    onChange({ doctorId, day, start: s.starts_at });
                  }}
                >
                  <bdi className="tabular">{formatDate(s.starts_at, language, "time")}</bdi>
                </Chip>
              ))}
            </div>
          )}
        </section>
      ) : null}
    </div>
  );
}
