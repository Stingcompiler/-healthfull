import { useNavigate } from "@tanstack/react-router";
import { CalendarCheck } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { AlertCard } from "@/components/AlertCard";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";
import { formatDate } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";
import { cn } from "@/lib/utils";

import { useBookAppointment, useBookingDays, useDoctors, useSlots } from "../api";
import { PortalPage, PortalSection } from "../components/PortalPage";
import { formatDay, usePick } from "../lib/ui";

/** A selectable option shown as a large button (radio semantics). */
function Choice({
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

/** Book a free slot: doctor, then day, then time (FEATURES 2.5, 15.2). */
export function BookAppointmentPage() {
  const { t } = useTranslation(["portal", "errors"]);
  const translateError = useTranslateError();
  const pick = usePick();
  const language = useLanguage();
  const navigate = useNavigate();
  const [doctorId, setDoctorId] = useState<number | null>(null);
  const [day, setDay] = useState<string | null>(null);
  const [start, setStart] = useState<string | null>(null);
  const doctors = useDoctors();
  const days = useBookingDays(doctorId);
  const slots = useSlots(doctorId, day);
  const book = useBookAppointment();
  const doctor = doctors.data?.find((d) => d.id === doctorId) ?? null;

  const submit = async () => {
    if (doctorId === null || start === null) return;
    await book.mutateAsync({ doctor_id: doctorId, starts_at: start });
    toast.success(t("book.booked"));
    await navigate({ to: "/portal/appointments" });
  };

  return (
    <PortalPage
      title={t("book.title")}
      description={t("book.description")}
      back={{ to: "/portal/appointments", label: t("book.back") }}
    >
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
                  setDoctorId(d.id);
                  setDay(null);
                  setStart(null);
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
                  setDay(d);
                  setStart(null);
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
                onSelect={() => setStart(s.starts_at)}
              >
                <bdi className="tabular">{formatDate(s.starts_at, language, "time")}</bdi>
              </Choice>
            ))}
          </div>
        )}
      </PortalSection>

      {book.isError ? <AlertCard variant="danger" title={translateError(book.error)} live /> : null}

      <div className="card-surface flex flex-col gap-3 p-4" data-testid="book-summary">
        {doctor && start ? (
          <p className="text-sm font-medium text-fg">
            {t("book.summary", {
              doctor: pick(doctor.name_ar, doctor.name_en),
              date: formatDate(start, language, "long"),
              time: formatDate(start, language, "time"),
            })}
          </p>
        ) : null}
        <Button
          size="lg"
          className="w-full"
          disabled={doctorId === null || start === null}
          loading={book.isPending}
          data-testid="book-confirm"
          onClick={() => {
            void submit().catch(() => undefined);
          }}
        >
          <CalendarCheck aria-hidden="true" />
          {t("book.confirm")}
        </Button>
      </div>
    </PortalPage>
  );
}
