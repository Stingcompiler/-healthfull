import { useNavigate, useParams } from "@tanstack/react-router";
import { CalendarCheck } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { AlertCard } from "@/components/AlertCard";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";
import { formatDate } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";

import { useAppointments, useBookAppointment, useDoctors, useRescheduleAppointment } from "../api";
import { PortalPage } from "../components/PortalPage";
import { SlotChooser } from "../components/SlotChooser";
import { usePick } from "../lib/ui";

/** Book a free slot: doctor, then day, then time (FEATURES 2.5, 15.2). */
export function BookAppointmentPage() {
  return <SlotPicker mode={{ kind: "book" }} />;
}

/** Move one's own confirmed booking to another free slot (ADR 0029 A7). */
export function RescheduleAppointmentPage() {
  const { appointmentId } = useParams({ strict: false });
  const appointments = useAppointments();
  const id = Number(appointmentId);
  const current = appointments.data?.upcoming.find((a) => a.id === id) ?? null;
  if (appointments.isPending) return <Skeleton className="h-40" />;
  return (
    <SlotPicker
      mode={{ kind: "reschedule", id, doctorId: current?.doctor.id ?? null, startsAt: current?.starts_at ?? null }}
    />
  );
}

type PickerMode =
  { kind: "book" } | { kind: "reschedule"; id: number; doctorId: number | null; startsAt: string | null };

function SlotPicker({ mode }: { mode: PickerMode }) {
  const { t } = useTranslation(["portal", "errors"]);
  const translateError = useTranslateError();
  const pick = usePick();
  const language = useLanguage();
  const navigate = useNavigate();
  const moving = mode.kind === "reschedule";
  const [doctorId, setDoctorId] = useState<number | null>(moving ? mode.doctorId : null);
  const [day, setDay] = useState<string | null>(null);
  const [start, setStart] = useState<string | null>(null);
  const doctors = useDoctors();
  const bookMutation = useBookAppointment();
  const moveMutation = useRescheduleAppointment();
  const book = moving ? moveMutation : bookMutation;
  const doctor = doctors.data?.find((d) => d.id === doctorId) ?? null;

  const submit = async () => {
    if (doctorId === null || start === null) return;
    const saved =
      mode.kind === "reschedule"
        ? await moveMutation.mutateAsync({ id: mode.id, body: { doctor_id: doctorId, starts_at: start } })
        : await bookMutation.mutateAsync({ doctor_id: doctorId, starts_at: start });
    toast.success(saved.status === "requested" ? t("book.requested") : moving ? t("book.moved") : t("book.booked"));
    await navigate({ to: "/portal/appointments" });
  };

  return (
    <PortalPage
      title={moving ? t("book.rescheduleTitle") : t("book.title")}
      description={
        mode.kind === "reschedule" && mode.startsAt
          ? t("book.rescheduleDescription", {
              date: formatDate(mode.startsAt, language, "long"),
              time: formatDate(mode.startsAt, language, "time"),
            })
          : t("book.description")
      }
      back={{ to: "/portal/appointments", label: t("book.back") }}
    >
      <SlotChooser
        value={{ doctorId, day, start }}
        onChange={(next) => {
          setDoctorId(next.doctorId);
          setDay(next.day);
          setStart(next.start);
        }}
      />

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
          {moving ? t("book.confirmMove") : t("book.confirm")}
        </Button>
      </div>
    </PortalPage>
  );
}
