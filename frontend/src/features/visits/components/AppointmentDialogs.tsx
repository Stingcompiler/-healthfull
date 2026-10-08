import { zodResolver } from "@hookform/resolvers/zod";
import { useState, type ReactNode } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { z } from "zod";

import { AlertCard } from "@/components/AlertCard";
import { DateText } from "@/components/DateText";
import { Form, SelectField, TextareaField, TextField } from "@/components/form";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useCoverages } from "@/features/patients/api";
import { PatientPicker } from "@/features/patients/components/PatientPicker";
import { centerToday, patientName } from "@/features/patients/lib";
import type { PatientListItem } from "@/features/patients/types";
import { toApiError } from "@/lib/api/errors";
import { useTranslateError } from "@/lib/api/translate-error";
import { formatDate } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";
import { requiredString, vmsg } from "@/lib/validation";

import { useAgenda, useBookAppointment, useCancelAppointment, useCheckIn, useRescheduleAppointment } from "../api";
import type { Appointment, Doctor, VisitDetail } from "../types";

function useDialogError() {
  const translateError = useTranslateError();
  const [error, setError] = useState<string | null>(null);
  return {
    error,
    clear: () => {
      setError(null);
    },
    fail: (e: unknown) => {
      setError(translateError(toApiError(e)));
    },
  };
}

function ErrorBox({ error }: { error: string | null }) {
  const { t } = useTranslation("errors");
  return error ? (
    <AlertCard variant="danger" title={t("title")} live>
      {error}
    </AlertCard>
  ) : null;
}

function DialogShell({
  open,
  onOpenChange,
  title,
  description,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description: ReactNode;
  children: ReactNode;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        {children}
      </DialogContent>
    </Dialog>
  );
}

function appointmentWho(a: Appointment, language: "ar" | "en"): string {
  return a.patient ? patientName(a.patient, language) : a.contact_name;
}

// --- book -----------------------------------------------------------------------------------

const bookSchema = z.object({
  contact_name: z.string().trim().max(200),
  contact_phone: z
    .string()
    .trim()
    .refine((v) => v === "" || /^0\d{9}$/.test(v), vmsg("validation.phone")),
  notes: z.string().trim().max(300),
});
type BookValues = z.infer<typeof bookSchema>;

export interface BookSlot {
  doctor: Doctor;
  startsAt: string;
  endsAt: string;
}

/** Book a free slot for a patient file or a caller without a file (FEATURES 2.5). */
export function BookAppointmentDialog({
  slot,
  onOpenChange,
}: {
  slot: BookSlot | null;
  onOpenChange: (open: boolean) => void;
}) {
  // Mounted only while a slot is chosen, so each booking starts from an empty form.
  return slot ? <BookBody slot={slot} onOpenChange={onOpenChange} /> : null;
}

function BookBody({ slot, onOpenChange }: { slot: BookSlot; onOpenChange: (open: boolean) => void }) {
  const { t } = useTranslation(["visits", "common"]);
  const language = useLanguage();
  const book = useBookAppointment();
  const { error, clear, fail } = useDialogError();
  const [mode, setMode] = useState<"patient" | "caller">("patient");
  const [patient, setPatient] = useState<PatientListItem | null>(null);
  const form = useForm<BookValues>({
    resolver: zodResolver(bookSchema),
    defaultValues: { contact_name: "", contact_phone: "", notes: "" },
  });

  const submit = form.handleSubmit(async (values) => {
    clear();
    if (mode === "patient" && !patient) {
      form.setError("root", { message: t("appointments.patientRequired") });
      return;
    }
    if (mode === "caller" && !values.contact_name) {
      form.setError("contact_name", { message: vmsg("validation.required") });
      return;
    }
    try {
      await book.mutateAsync({
        doctor_id: slot.doctor.id,
        starts_at: slot.startsAt,
        patient_id: mode === "patient" ? (patient?.id ?? null) : null,
        contact_name: mode === "caller" ? values.contact_name : "",
        contact_phone: mode === "caller" ? values.contact_phone : "",
        notes: values.notes,
      });
      toast.success(t("appointments.booked"));
      onOpenChange(false);
    } catch (e) {
      fail(e);
    }
  });

  return (
    <DialogShell
      open
      onOpenChange={onOpenChange}
      title={t("appointments.bookTitle")}
      description={
        <>
          {pickName({ ar: slot.doctor.name_ar, en: slot.doctor.name_en }, language)} ·{" "}
          {formatDate(slot.startsAt, language, "datetime")}
        </>
      }
    >
      <Form {...form}>
        <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4">
          <Tabs
            value={mode}
            onValueChange={(v) => {
              setMode(v === "caller" ? "caller" : "patient");
            }}
          >
            <TabsList className="w-full">
              <TabsTrigger value="patient">{t("appointments.forPatient")}</TabsTrigger>
              <TabsTrigger value="caller">{t("appointments.forCaller")}</TabsTrigger>
            </TabsList>
            <TabsContent value="patient" className="pt-3">
              <PatientPicker value={patient} onChange={setPatient} />
              {form.formState.errors.root ? (
                <p className="mt-2 text-sm text-danger-fg">{form.formState.errors.root.message}</p>
              ) : null}
            </TabsContent>
            <TabsContent value="caller" className="grid gap-4 pt-3 sm:grid-cols-2">
              <TextField control={form.control} name="contact_name" label={t("appointments.contactName")} required />
              <TextField
                control={form.control}
                name="contact_phone"
                label={t("appointments.contactPhone")}
                type="tel"
                dir="ltr"
              />
            </TabsContent>
          </Tabs>
          <TextField control={form.control} name="notes" label={t("appointments.notes")} />
          <ErrorBox error={error} />
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                onOpenChange(false);
              }}
            >
              {t("common:actions.cancel")}
            </Button>
            <Button type="submit" loading={book.isPending}>
              {t("appointments.book")}
            </Button>
          </DialogFooter>
        </form>
      </Form>
    </DialogShell>
  );
}

// --- reschedule -----------------------------------------------------------------------------

/** Move a booking to a free slot of the same doctor on any day. */
export function RescheduleDialog({
  appointment,
  onOpenChange,
}: {
  appointment: Appointment | null;
  onOpenChange: (open: boolean) => void;
}) {
  return appointment ? <RescheduleBody appointment={appointment} onOpenChange={onOpenChange} /> : null;
}

function RescheduleBody({
  appointment,
  onOpenChange,
}: {
  appointment: Appointment;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation(["visits", "common"]);
  const language = useLanguage();
  const reschedule = useRescheduleAppointment();
  const { error, clear, fail } = useDialogError();
  const [day, setDay] = useState(() => centerToday(new Date(appointment.starts_at)));
  const [slot, setSlot] = useState("");
  const agenda = useAgenda(appointment.doctor.id, day || "1970-01-01");
  const free = day ? (agenda.data?.items ?? []).filter((i) => i.appointment === null) : [];

  const submit = async () => {
    if (!slot) return;
    clear();
    try {
      await reschedule.mutateAsync({ id: appointment.id, startsAt: slot });
      toast.success(t("appointments.rescheduled"));
      onOpenChange(false);
    } catch (e) {
      fail(e);
    }
  };

  return (
    <DialogShell
      open
      onOpenChange={onOpenChange}
      title={t("appointments.rescheduleTitle")}
      description={`${appointmentWho(appointment, language)} · ${formatDate(appointment.starts_at, language, "datetime")}`}
    >
      <div className="grid gap-4">
        <div className="grid gap-1.5">
          <Label htmlFor="reschedule-day">{t("appointments.newDay")}</Label>
          <Input
            id="reschedule-day"
            type="date"
            dir="ltr"
            value={day}
            onChange={(e) => {
              setDay(e.target.value);
              setSlot("");
            }}
          />
        </div>
        <div className="grid gap-1.5">
          <Label>{t("appointments.newSlot")}</Label>
          {free.length > 0 ? (
            <div className="flex flex-wrap gap-2" role="radiogroup" aria-label={t("appointments.newSlot")}>
              {free.map((i) => (
                <Button
                  key={i.starts_at}
                  type="button"
                  size="sm"
                  role="radio"
                  aria-checked={slot === i.starts_at}
                  variant={slot === i.starts_at ? "default" : "outline"}
                  onClick={() => {
                    setSlot(i.starts_at);
                  }}
                >
                  <DateText value={i.starts_at} format="time" />
                </Button>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted">
              {agenda.isFetching ? t("appointments.loadingSlots") : t("appointments.noFreeSlots")}
            </p>
          )}
        </div>
        <ErrorBox error={error} />
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              onOpenChange(false);
            }}
          >
            {t("common:actions.cancel")}
          </Button>
          <Button type="button" disabled={!slot} loading={reschedule.isPending} onClick={() => void submit()}>
            {t("appointments.reschedule")}
          </Button>
        </DialogFooter>
      </div>
    </DialogShell>
  );
}

// --- cancel ---------------------------------------------------------------------------------

const cancelSchema = z.object({ note: requiredString.max(300) });

/** Cancel a booking with the caller's reason (invariant 4: reason, who, when). */
export function CancelAppointmentDialog({
  appointment,
  onOpenChange,
}: {
  appointment: Appointment | null;
  onOpenChange: (open: boolean) => void;
}) {
  return appointment ? <CancelBody appointment={appointment} onOpenChange={onOpenChange} /> : null;
}

function CancelBody({
  appointment,
  onOpenChange,
}: {
  appointment: Appointment;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation(["visits", "common"]);
  const language = useLanguage();
  const cancel = useCancelAppointment();
  const { error, clear, fail } = useDialogError();
  const form = useForm<{ note: string }>({ resolver: zodResolver(cancelSchema), defaultValues: { note: "" } });

  const submit = form.handleSubmit(async ({ note }) => {
    clear();
    try {
      await cancel.mutateAsync({ id: appointment.id, note });
      toast.success(t("appointments.cancelled"));
      onOpenChange(false);
    } catch (e) {
      fail(e);
    }
  });

  return (
    <DialogShell
      open
      onOpenChange={onOpenChange}
      title={t("appointments.cancelTitle")}
      description={`${appointmentWho(appointment, language)} · ${formatDate(appointment.starts_at, language, "datetime")}`}
    >
      <Form {...form}>
        <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4">
          <TextareaField
            control={form.control}
            name="note"
            label={t("appointments.cancelReason")}
            required
            rows={3}
            maxLength={300}
          />
          <ErrorBox error={error} />
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                onOpenChange(false);
              }}
            >
              {t("common:actions.back")}
            </Button>
            <Button type="submit" variant="destructive" loading={cancel.isPending}>
              {t("appointments.cancel")}
            </Button>
          </DialogFooter>
        </form>
      </Form>
    </DialogShell>
  );
}

// --- check-in -------------------------------------------------------------------------------

const checkInSchema = z.object({
  coverage: z.string(),
  card_number: z.string().trim().max(60),
  chief_complaint: z.string().trim().max(300),
});
type CheckInValues = z.infer<typeof checkInSchema>;

/** The patient arrived: open the visit from the booking (FEATURES 2.5). */
export function CheckInDialog({
  appointment,
  onOpenChange,
  onCheckedIn,
}: {
  appointment: Appointment | null;
  onOpenChange: (open: boolean) => void;
  onCheckedIn?: (visit: VisitDetail) => void;
}) {
  return appointment ? (
    <CheckInBody appointment={appointment} onOpenChange={onOpenChange} onCheckedIn={onCheckedIn} />
  ) : null;
}

function CheckInBody({
  appointment,
  onOpenChange,
  onCheckedIn,
}: {
  appointment: Appointment;
  onOpenChange: (open: boolean) => void;
  onCheckedIn?: ((visit: VisitDetail) => void) | undefined;
}) {
  const { t } = useTranslation(["visits", "common"]);
  const language = useLanguage();
  const checkIn = useCheckIn();
  const { error, clear, fail } = useDialogError();
  const [patient, setPatient] = useState<PatientListItem | null>(null);
  const booked = appointment.patient;
  const patientId = booked?.id ?? patient?.id ?? null;
  const coverages = useCoverages(patientId ?? 0, false, patientId !== null);
  const form = useForm<CheckInValues>({
    resolver: zodResolver(checkInSchema),
    defaultValues: { coverage: "default", card_number: "", chief_complaint: "" },
  });

  const submit = form.handleSubmit(async (values) => {
    clear();
    const coverageId = values.coverage === "default" || values.coverage === "cash" ? null : Number(values.coverage);
    try {
      const visit = await checkIn.mutateAsync({
        id: appointment.id,
        body: {
          patient_id: booked ? null : (patient?.id ?? null),
          coverage_id: coverageId,
          use_default_coverage: values.coverage === "default",
          card_number: values.card_number,
          chief_complaint: values.chief_complaint,
        },
      });
      toast.success(t("appointments.checkedIn", { number: visit.visit.number }));
      onOpenChange(false);
      onCheckedIn?.(visit);
    } catch (e) {
      fail(e);
    }
  });

  return (
    <DialogShell
      open
      onOpenChange={onOpenChange}
      title={t("appointments.checkInTitle")}
      description={`${appointmentWho(appointment, language)} · ${formatDate(appointment.starts_at, language, "datetime")}`}
    >
      <Form {...form}>
        <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4">
          {booked ? null : (
            <div className="grid gap-2">
              <Label>{t("appointments.fileForCaller")}</Label>
              <PatientPicker value={patient} onChange={setPatient} />
            </div>
          )}
          <div className="grid gap-4 sm:grid-cols-2">
            <SelectField
              control={form.control}
              name="coverage"
              label={t("create.coverage")}
              options={[
                { value: "default", label: t("create.coverageDefault") },
                { value: "cash", label: t("create.coverageCash") },
                ...(coverages.data ?? []).map((c) => ({
                  value: String(c.id),
                  label: [pickName({ ar: c.payer.name_ar, en: c.payer.name_en }, language), c.card_number]
                    .filter(Boolean)
                    .join(" · "),
                })),
              ]}
            />
            <TextField control={form.control} name="card_number" label={t("create.cardNumber")} dir="ltr" />
          </div>
          <TextField control={form.control} name="chief_complaint" label={t("create.complaint")} />
          <ErrorBox error={error} />
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                onOpenChange(false);
              }}
            >
              {t("common:actions.cancel")}
            </Button>
            <Button type="submit" loading={checkIn.isPending}>
              {t("appointments.checkIn")}
            </Button>
          </DialogFooter>
        </form>
      </Form>
    </DialogShell>
  );
}
