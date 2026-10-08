import { Link } from "@tanstack/react-router";
import {
  Ban,
  CalendarClock,
  CalendarDays,
  CalendarPlus,
  CalendarX2,
  CheckCircle2,
  DoorOpen,
  MoreHorizontal,
  Phone,
  UserX,
} from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { ChevronNext, ChevronPrev } from "@/components/icons";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { addDays, centerToday, patientName } from "@/features/patients/lib";
import { toApiError } from "@/lib/api/errors";
import { useTranslateError } from "@/lib/api/translate-error";
import { usePermission } from "@/lib/auth/hooks";
import { formatDate } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

import { useAgenda, useAppointmentNoShow, useVisitOptions } from "../api";
import {
  BookAppointmentDialog,
  CancelAppointmentDialog,
  CheckInDialog,
  RescheduleDialog,
  type BookSlot,
} from "../components/AppointmentDialogs";
import { TokenSlipDialog } from "../components/TokenSlipDialog";
import { useDeviceChoice } from "../lib";
import type { AgendaItem, Appointment } from "../types";

const STATUS_VARIANT = {
  booked: "info",
  arrived: "success",
  cancelled: "outline",
  no_show: "danger",
  rescheduled: "neutral",
} as const;

/** A doctor's day (FEATURES 2.5): free slots to book, bookings to reschedule, cancel or check in. */
export function AppointmentsPage() {
  const { t } = useTranslation(["visits", "common"]);
  const language = useLanguage();
  const translateError = useTranslateError();
  const options = useVisitOptions();
  const [storedDoctor, setDoctorId] = useDeviceChoice("agendaDoctor");
  const doctors = options.data?.doctors ?? [];
  const doctorId =
    storedDoctor !== null && doctors.some((d) => d.id === storedDoctor) ? storedDoctor : (doctors[0]?.id ?? null);
  const doctor = doctors.find((d) => d.id === doctorId) ?? null;
  const today = centerToday();
  const [day, setDay] = useState(today);
  const agenda = useAgenda(doctorId, day);
  const noShow = useAppointmentNoShow();
  const canCheckIn = usePermission("visits.create");

  const [booking, setBooking] = useState<BookSlot | null>(null);
  const [rescheduling, setRescheduling] = useState<Appointment | null>(null);
  const [cancelling, setCancelling] = useState<Appointment | null>(null);
  const [checkingIn, setCheckingIn] = useState<Appointment | null>(null);
  const [tokenEntry, setTokenEntry] = useState<number | null>(null);

  const items = agenda.data?.items ?? [];

  const markNoShow = async (a: Appointment) => {
    try {
      await noShow.mutateAsync(a.id);
      toast.success(t("appointments.markedNoShow"));
    } catch (e) {
      toast.error(translateError(toApiError(e)));
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <PageHeader icon={<CalendarDays />} title={t("appointments.title")} description={t("appointments.description")} />

      <div className="flex flex-col gap-3 md:flex-row md:items-end">
        <div className="grid gap-1.5 md:w-72">
          <Label htmlFor="agenda-doctor">{t("appointments.doctor")}</Label>
          <Select
            value={doctorId ? String(doctorId) : ""}
            onValueChange={(v) => {
              setDoctorId(Number(v));
            }}
          >
            <SelectTrigger id="agenda-doctor">
              <SelectValue placeholder={t("appointments.pickDoctor")} />
            </SelectTrigger>
            <SelectContent>
              {doctors.map((d) => (
                <SelectItem key={d.id} value={String(d.id)}>
                  {pickName({ ar: d.name_ar, en: d.name_en }, language)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="agenda-day">{t("appointments.day")}</Label>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="icon"
              aria-label={t("appointments.previousDay")}
              onClick={() => {
                setDay(addDays(day, -1));
              }}
            >
              <ChevronPrev aria-hidden="true" />
            </Button>
            <Input
              id="agenda-day"
              type="date"
              dir="ltr"
              className="w-auto min-w-0 flex-1 sm:w-44 sm:flex-none"
              value={day}
              onChange={(e) => {
                if (e.target.value) setDay(e.target.value);
              }}
            />
            <Button
              type="button"
              variant="outline"
              size="icon"
              aria-label={t("appointments.nextDay")}
              onClick={() => {
                setDay(addDays(day, 1));
              }}
            >
              <ChevronNext aria-hidden="true" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              disabled={day === today}
              onClick={() => {
                setDay(today);
              }}
            >
              {t("appointments.today")}
            </Button>
          </div>
        </div>
      </div>

      <section aria-labelledby="agenda-heading" className="flex flex-col gap-3">
        <h2 id="agenda-heading" className="text-base font-semibold text-fg">
          {doctor
            ? t("appointments.dayOf", {
                doctor: pickName({ ar: doctor.name_ar, en: doctor.name_en }, language),
                day: formatDate(`${day}T12:00:00`, language, "long"),
              })
            : t("appointments.pickDoctor")}
        </h2>
        {agenda.isPending && doctorId !== null ? (
          <div className="grid gap-2">
            <Skeleton className="h-16" />
            <Skeleton className="h-16" />
          </div>
        ) : items.length === 0 ? (
          <EmptyState
            icon={<CalendarX2 />}
            title={agenda.data?.works === false ? t("appointments.offDayTitle") : t("appointments.noSlotsTitle")}
            description={
              agenda.data?.works === false ? t("appointments.offDayDescription") : t("appointments.noSlotsDescription")
            }
            action={
              <Button
                variant="outline"
                onClick={() => {
                  setDay(addDays(day, 1));
                }}
              >
                {t("appointments.nextDay")}
              </Button>
            }
          />
        ) : (
          <ul className="grid gap-2" aria-label={t("appointments.agenda")}>
            {items.map((item) => (
              <li key={item.appointment ? `a${String(item.appointment.id)}` : `s${item.starts_at}`}>
                {item.appointment ? (
                  <AppointmentRow
                    item={item}
                    appointment={item.appointment}
                    canCheckIn={canCheckIn}
                    onCheckIn={setCheckingIn}
                    onReschedule={setRescheduling}
                    onCancel={setCancelling}
                    onNoShow={(a) => void markNoShow(a)}
                  />
                ) : (
                  <div
                    className="flex items-center gap-3 rounded-card border border-dashed border-border-strong px-4 py-3"
                    data-testid="free-slot"
                  >
                    <span className="w-24 shrink-0 tabular text-sm font-medium text-fg">
                      <DateText value={item.starts_at} format="time" />
                    </span>
                    <span className="min-w-0 flex-1 text-sm text-muted">{t("appointments.free")}</span>
                    {doctor ? (
                      <Button
                        size="sm"
                        variant="soft"
                        aria-label={t("appointments.bookAt", { time: formatDate(item.starts_at, language, "time") })}
                        onClick={() => {
                          setBooking({ doctor, startsAt: item.starts_at, endsAt: item.ends_at });
                        }}
                      >
                        <CalendarPlus aria-hidden="true" />
                        {t("appointments.book")}
                      </Button>
                    ) : null}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <BookAppointmentDialog
        slot={booking}
        onOpenChange={(open) => {
          if (!open) setBooking(null);
        }}
      />
      <RescheduleDialog
        appointment={rescheduling}
        onOpenChange={(open) => {
          if (!open) setRescheduling(null);
        }}
      />
      <CancelAppointmentDialog
        appointment={cancelling}
        onOpenChange={(open) => {
          if (!open) setCancelling(null);
        }}
      />
      <CheckInDialog
        appointment={checkingIn}
        onOpenChange={(open) => {
          if (!open) setCheckingIn(null);
        }}
        onCheckedIn={(visit) => {
          if (visit.queue_entry) setTokenEntry(visit.queue_entry.id);
        }}
      />
      <TokenSlipDialog
        entryId={tokenEntry}
        onOpenChange={(open) => {
          if (!open) setTokenEntry(null);
        }}
      />
    </div>
  );
}

function AppointmentRow({
  item,
  appointment: a,
  canCheckIn,
  onCheckIn,
  onReschedule,
  onCancel,
  onNoShow,
}: {
  item: AgendaItem;
  appointment: Appointment;
  canCheckIn: boolean;
  onCheckIn: (a: Appointment) => void;
  onReschedule: (a: Appointment) => void;
  onCancel: (a: Appointment) => void;
  onNoShow: (a: Appointment) => void;
}) {
  const { t } = useTranslation(["visits", "common"]);
  const language = useLanguage();
  const name = a.patient ? patientName(a.patient, language) : a.contact_name;
  const phone = a.patient ? a.patient.phone : a.contact_phone;
  const open = a.status === "booked";
  return (
    <div className="card-surface flex flex-wrap items-start gap-3 p-4" data-testid="appointment" data-status={a.status}>
      <span className="w-24 shrink-0 pt-0.5 tabular text-sm font-semibold text-fg">
        <DateText value={item.starts_at} format="time" />
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        {a.patient ? (
          <Link
            to="/patients/$patientId"
            params={{ patientId: String(a.patient.id) }}
            className="font-semibold break-words text-fg underline-offset-4 hover:underline"
          >
            {name}
          </Link>
        ) : (
          <span className="font-semibold break-words text-fg">{name}</span>
        )}
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
          {a.patient ? <bdi className="tabular">{a.patient.file_no}</bdi> : <span>{t("appointments.noFile")}</span>}
          {phone ? (
            <span className="inline-flex items-center gap-1">
              <Phone className="size-3.5" aria-hidden="true" />
              <bdi className="tabular">{phone}</bdi>
            </span>
          ) : null}
        </span>
        {a.notes ? <p className="text-sm break-words text-fg">{a.notes}</p> : null}
        {a.status === "cancelled" && a.cancel_note ? (
          <p className="text-xs break-words text-muted">
            {t("appointments.cancelledBecause", { note: a.cancel_note })}
          </p>
        ) : null}
        <span>
          <Badge variant={STATUS_VARIANT[a.status]}>{t(`appointmentStatus.${a.status}`)}</Badge>
        </span>
      </div>
      {open ? (
        <div className="flex items-center gap-2 max-sm:basis-full max-sm:justify-end">
          {canCheckIn ? (
            <Button
              size="sm"
              onClick={() => {
                onCheckIn(a);
              }}
            >
              <DoorOpen aria-hidden="true" />
              {t("appointments.checkIn")}
            </Button>
          ) : null}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="sm" variant="outline" aria-label={t("appointments.moreFor", { name })}>
                <MoreHorizontal aria-hidden="true" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem
                onSelect={() => {
                  onReschedule(a);
                }}
              >
                <CalendarClock aria-hidden="true" />
                {t("appointments.reschedule")}
              </DropdownMenuItem>
              <DropdownMenuItem
                onSelect={() => {
                  onNoShow(a);
                }}
              >
                <UserX aria-hidden="true" />
                {t("appointments.noShow")}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                variant="destructive"
                onSelect={() => {
                  onCancel(a);
                }}
              >
                <Ban aria-hidden="true" />
                {t("appointments.cancel")}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      ) : a.status === "arrived" ? (
        <CheckCircle2 className="size-5 text-success" aria-hidden="true" />
      ) : null}
    </div>
  );
}
