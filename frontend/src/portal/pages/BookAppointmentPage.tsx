import { useNavigate, useParams } from "@tanstack/react-router";
import { CalendarCheck } from "lucide-react";
import { useRef, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { AlertCard } from "@/components/AlertCard";
import { ChevronsNext } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";
import { formatDate } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";

import { useAppointments, useBookAppointment, useDoctors, useRescheduleAppointment } from "../api";
import {
  ActionBar,
  BackButton,
  ChoiceSummary,
  FeesAndPolicy,
  SiteCard,
  StepLayout,
  Stepper,
} from "../components/BookingParts";
import { PortalPage, Row } from "../components/PortalPage";
import { SiteSlotChooser, type SlotChoice } from "../components/SlotChooser";
import { PATIENT_STEPS, slotComplete, type PatientStep } from "../guest/steps";
import { useDoctorDetail, usePick } from "../lib/ui";
import type { PortalDoctor } from "../types";

/** Book a free slot: doctor, then day, then time, then a review (FEATURES 2.5, 15.2; D-0024). */
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

/**
 * The signed-in booking in the guest booking's design (D-0024), inside the portal's own header and
 * tab bar: a two-step stepper (doctor and time, then review), the website's slot chooser, from lg
 * a sticky summary beside the step (the choice, fees at reception, the cancellation policy), and
 * on phones the step's actions in a glass bar above the tab bar. Same calls as before (book or
 * move), then the appointments list with a notice.
 */
function SlotPicker({ mode }: { mode: PickerMode }) {
  const { t } = useTranslation(["portal", "errors"]);
  const translateError = useTranslateError();
  const pick = usePick();
  const language = useLanguage();
  const navigate = useNavigate();
  const moving = mode.kind === "reschedule";
  const [step, setStep] = useState<PatientStep>("slot");
  const [choice, setChoice] = useState<SlotChoice>({
    doctorId: moving ? mode.doctorId : null,
    day: null,
    start: null,
  });
  const { doctorId, start } = choice;
  const doctors = useDoctors();
  const bookMutation = useBookAppointment();
  const moveMutation = useRescheduleAppointment();
  const book = moving ? moveMutation : bookMutation;
  const doctor = doctors.data?.find((d) => d.id === doctorId) ?? null;
  const heading = useRef<HTMLHeadingElement>(null);
  const top = useRef<HTMLDivElement>(null);
  const stepLabel = (s: PatientStep) => t(`book.steps.${s}`);

  const go = (next: PatientStep) => {
    setStep(next);
    // As in the guest booking: focus the new step's heading and bring the stepper back into view.
    requestAnimationFrame(() => {
      top.current?.scrollIntoView({ block: "start" });
      heading.current?.focus({ preventScroll: true });
    });
  };

  const submit = async () => {
    if (doctorId === null || start === null) return;
    const saved =
      mode.kind === "reschedule"
        ? await moveMutation.mutateAsync({ id: mode.id, body: { doctor_id: doctorId, starts_at: start } })
        : await bookMutation.mutateAsync({ doctor_id: doctorId, starts_at: start });
    toast.success(saved.status === "requested" ? t("book.requested") : moving ? t("book.moved") : t("book.booked"));
    await navigate({ to: "/portal/appointments" });
  };

  const slotSummary =
    doctor && start
      ? t("book.summary", {
          doctor: pick(doctor.name_ar, doctor.name_en),
          date: formatDate(start, language, "long"),
          time: formatDate(start, language, "time"),
        })
      : null;

  // The booking being moved, kept in view beside the new choice.
  const currentRow =
    mode.kind === "reschedule" && mode.startsAt ? (
      <Row label={t("book.currentAppointment")}>
        <span className="flex flex-col">
          <span>{formatDate(mode.startsAt, language, "long")}</span>
          <bdi className="tabular">{formatDate(mode.startsAt, language, "time")}</bdi>
        </span>
      </Row>
    ) : null;

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
      <div className="flex min-w-0 flex-col gap-5">
        <div ref={top} className="scroll-mt-20">
          <Stepper steps={PATIENT_STEPS} current={step} labelOf={stepLabel} testId="book-step" />
        </div>

        {step === "slot" ? (
          <StepLayout
            main={
              <>
                <SiteCard title={stepLabel("slot")} titleId="book-step-title" titleRef={heading}>
                  <SiteSlotChooser value={choice} onChange={setChoice} />
                </SiteCard>
                <ActionBar
                  aboveTabBar
                  testId="book-action-bar"
                  note={slotSummary ? <p className="truncate">{slotSummary}</p> : null}
                >
                  <Button
                    size="lg"
                    className="w-full lg:ms-auto lg:w-auto"
                    disabled={!slotComplete(choice)}
                    data-testid="book-next"
                    onClick={() => {
                      go("review");
                    }}
                  >
                    {t("guest.next")}
                    <ChevronsNext />
                  </Button>
                </ActionBar>
              </>
            }
            side={<ChoiceSummary choice={choice} before={currentRow} />}
          />
        ) : null}

        {step === "review" && start ? (
          <StepLayout
            testId="book-review-step"
            main={
              <>
                <SiteCard title={stepLabel("review")} titleId="book-step-title" titleRef={heading}>
                  <ReviewRows doctor={doctor} start={start} before={currentRow} />
                  <p className="text-sm text-pretty text-muted">{t("book.reviewHint")}</p>
                  {book.isError ? <AlertCard variant="danger" title={translateError(book.error)} live /> : null}
                </SiteCard>
                <ActionBar aboveTabBar testId="book-action-bar">
                  <BackButton
                    disabled={book.isPending}
                    onClick={() => {
                      go("slot");
                    }}
                  />
                  <Button
                    size="lg"
                    className="min-w-0 flex-1 lg:flex-none"
                    loading={book.isPending}
                    data-testid="book-confirm"
                    onClick={() => {
                      void submit().catch(() => undefined);
                    }}
                  >
                    <CalendarCheck aria-hidden="true" />
                    {moving ? t("book.confirmMove") : t("book.confirm")}
                  </Button>
                </ActionBar>
              </>
            }
            side={<FeesAndPolicy />}
          />
        ) : null}
      </div>
    </PortalPage>
  );
}

/** The review's rows; a doctor no longer listed for booking (a moved booking) reads "—". */
function ReviewRows({ doctor, start, before }: { doctor: PortalDoctor | null; start: string; before: ReactNode }) {
  const { t } = useTranslation("portal");
  const pick = usePick();
  const detail = useDoctorDetail();
  const language = useLanguage();
  const sub = doctor ? detail(doctor) : "";
  return (
    <dl className="divide-y divide-border" data-testid="book-review">
      {before}
      <Row label={t("book.doctor")}>
        <span className="flex flex-col">
          <span className="font-semibold">{doctor ? pick(doctor.name_ar, doctor.name_en) : "—"}</span>
          {sub ? <span className="text-xs text-muted">{sub}</span> : null}
        </span>
      </Row>
      <Row label={t("book.day")}>{formatDate(start, language, "long")}</Row>
      <Row label={t("book.time")}>
        <bdi className="tabular">{formatDate(start, language, "time")}</bdi>
      </Row>
    </dl>
  );
}
