import { zodResolver } from "@hookform/resolvers/zod";
import { Link } from "@tanstack/react-router";
import { CalendarCheck, KeyRound, MessageCircle, Printer, ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { Form, TextField } from "@/components/form";
import { ChevronsNext } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { toApiError } from "@/lib/api/errors";
import { useTranslateError } from "@/lib/api/translate-error";
import { formatDate } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";

import { useDoctors } from "../api";
import {
  ActionBar,
  BackButton,
  ChoiceSummary,
  FeesAndPolicy,
  GuestEntryLinks,
  GuestStepper,
  SiteCard,
  StepLayout,
} from "../components/BookingParts";
import { Pill, PortalPage, Row } from "../components/PortalPage";
import { SiteSlotChooser, type SlotChoice } from "../components/SlotChooser";
import { createGuestBooking, fetchChallenge, type GuestBookingCreated } from "../guest/api";
import {
  attemptFor,
  clearAttempt,
  endsAttempt,
  loadAttempt,
  withProof,
  type Attempt,
  type AttemptDetails,
} from "../guest/attempt";
import { guestContactSchema, type GuestContactValues } from "../guest/form";
import { expectedTries } from "../guest/pow";
import { solveChallenge } from "../guest/solver";
import { slotComplete } from "../guest/steps";
import { BOOKING_TONE } from "../lib/tones";
import { useDoctorDetail, usePick } from "../lib/ui";

type Step = "slot" | "contact" | "review";

/**
 * `/portal/book`: booking without a patient file (ADR 0029 D, plan Phase 4; layout D-0023).
 * A stepper (doctor and time, your details, review, confirmation) over the step; from lg the
 * step sits beside a sticky summary with "fees are paid at reception" and the cancellation
 * policy, and on phones the step's actions float in a glass bar. The confirmation shows the
 * reference and the PIN once.
 *
 * The request carries an `Idempotency-Key` made once per attempt and kept in sessionStorage
 * (`guest/attempt.ts`), so a retry after a lost answer gets the same booking back. Before
 * sending, the browser solves the server's proof-of-work in a worker (`guest/solver.ts`) with
 * a bundled SHA-256 (plain-HTTP LAN installs have no `crypto.subtle`), showing its progress.
 */
export function GuestBookPage() {
  const { t } = useTranslation(["portal", "errors"]);
  const [created, setCreated] = useState<GuestBookingCreated | null>(null);
  const [pending, setPending] = useState<Attempt | null>(() => loadAttempt());

  if (created) {
    return <GuestConfirmation booking={created} />;
  }
  return (
    <PortalPage
      title={t("guest.title")}
      description={t("guest.description")}
      back={{ to: "/portal", label: t("login.centerLink") }}
    >
      <GuestEntryLinks />
      {pending ? (
        <ResumeAttempt
          attempt={pending}
          onDone={setCreated}
          onDiscard={() => {
            clearAttempt();
            setPending(null);
          }}
        />
      ) : (
        <GuestBookingFlow onDone={setCreated} />
      )}
    </PortalPage>
  );
}

interface SendState {
  phase: "idle" | "checking" | "sending";
  percent: number;
}

/**
 * Sends an attempt: solves its proof-of-work once (kept with the attempt), then posts it with
 * its key. An answer from the server ends the attempt; a lost answer keeps it for a retry.
 */
function useSendAttempt(onDone: (booking: GuestBookingCreated) => void) {
  const [state, setState] = useState<SendState>({ phase: "idle", percent: 0 });
  const [error, setError] = useState<unknown>(null);
  const [retryable, setRetryable] = useState(false);
  const abort = useRef<AbortController | null>(null);

  useEffect(
    () => () => {
      abort.current?.abort();
    },
    [],
  );

  const send = async (attempt: Attempt) => {
    setError(null);
    setRetryable(false);
    let current = attempt;
    try {
      if (!current.proof) {
        setState({ phase: "checking", percent: 0 });
        const challenge = await fetchChallenge();
        const expected = expectedTries(challenge.bits);
        abort.current = new AbortController();
        const nonce = await solveChallenge(
          { token: challenge.challenge, bits: challenge.bits },
          {
            signal: abort.current.signal,
            onProgress: (tried) => {
              // Tries needed vary; the bar slows near the end instead of stopping at 100%.
              const percent = Math.min(99, Math.round((1 - Math.exp(-tried / expected)) * 100));
              setState({ phase: "checking", percent });
            },
          },
        );
        current = withProof(current, { challenge: challenge.challenge, nonce });
      }
      setState({ phase: "sending", percent: 100 });
      const booking = await createGuestBooking(
        current.key,
        current.details,
        current.proof ?? { challenge: "", nonce: "" },
      );
      clearAttempt();
      onDone(booking);
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") return;
      const apiError = toApiError(caught);
      // A refusal ends the attempt (its challenge is spent); a lost answer may be retried as is.
      if (endsAttempt(apiError.status)) {
        clearAttempt();
      } else {
        setRetryable(true);
      }
      setError(apiError);
    } finally {
      setState({ phase: "idle", percent: 0 });
    }
  };

  return { state, error, retryable, send };
}

function SendProgress({ state }: { state: SendState }) {
  const { t } = useTranslation("portal");
  if (state.phase === "idle") return null;
  return (
    <div className="flex flex-col gap-2" role="status" aria-live="polite" data-testid="guest-progress">
      <p className="text-sm text-fg">
        {state.phase === "checking" ? t("guest.checking", { percent: String(state.percent) }) : t("guest.sending")}
      </p>
      <div className="h-2 overflow-hidden rounded-full bg-subtle" aria-hidden="true">
        <div className="h-full bg-primary transition-[width]" style={{ width: `${String(state.percent)}%` }} />
      </div>
    </div>
  );
}

/** A request whose answer was lost (reload, timeout): send the very same one again. */
function ResumeAttempt({
  attempt,
  onDone,
  onDiscard,
}: {
  attempt: Attempt;
  onDone: (booking: GuestBookingCreated) => void;
  onDiscard: () => void;
}) {
  const { t } = useTranslation(["portal", "errors"]);
  const translateError = useTranslateError();
  const { state, error, retryable, send } = useSendAttempt(onDone);
  const busy = state.phase !== "idle";
  return (
    <StepLayout
      main={
        <SiteCard title={t("guest.resume.title")} titleId="guest-resume-title" testId="guest-resume">
          <p className="text-sm text-pretty text-fg">{t("guest.resume.text")}</p>
          <ReviewRows details={attempt.details} />
          <SendProgress state={state} />
          {error ? <AlertCard variant="danger" title={translateError(error)} live /> : null}
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-between">
            <Button variant="outline" disabled={busy} onClick={onDiscard} data-testid="guest-resume-discard">
              {t("guest.resume.discard")}
            </Button>
            {error && !retryable ? null : (
              <Button
                size="lg"
                loading={busy}
                data-testid="guest-resume-send"
                onClick={() => {
                  void send(attempt);
                }}
              >
                {t("guest.resume.send")}
              </Button>
            )}
          </div>
        </SiteCard>
      }
      side={<FeesAndPolicy />}
    />
  );
}

function ReviewRows({ details }: { details: AttemptDetails }) {
  const { t } = useTranslation("portal");
  const pick = usePick();
  const language = useLanguage();
  const doctors = useDoctors();
  const doctor = doctors.data?.find((d) => d.id === details.doctor_id) ?? null;
  return (
    <dl className="divide-y divide-border" data-testid="guest-review">
      <Row label={t("book.doctor")}>{doctor ? pick(doctor.name_ar, doctor.name_en) : "—"}</Row>
      <Row label={t("book.day")}>{formatDate(details.starts_at, language, "long")}</Row>
      <Row label={t("book.time")}>
        <bdi className="tabular">{formatDate(details.starts_at, language, "time")}</bdi>
      </Row>
      <Row label={t("guest.form.name")}>{details.contact_name}</Row>
      <Row label={t("guest.form.phone")}>
        <bdi className="num">{details.contact_phone}</bdi>
      </Row>
    </dl>
  );
}

function GuestBookingFlow({ onDone }: { onDone: (booking: GuestBookingCreated) => void }) {
  const { t } = useTranslation(["portal", "errors", "common"]);
  const translateError = useTranslateError();
  const pick = usePick();
  const language = useLanguage();
  const [step, setStep] = useState<Step>("slot");
  const [choice, setChoice] = useState<SlotChoice>({ doctorId: null, day: null, start: null });
  const [contact, setContact] = useState<GuestContactValues>({ contact_name: "", contact_phone: "" });
  const doctors = useDoctors();
  const doctor = doctors.data?.find((d) => d.id === choice.doctorId) ?? null;
  const { state, error, retryable, send } = useSendAttempt(onDone);
  const busy = state.phase !== "idle";
  const form = useForm<GuestContactValues>({ resolver: zodResolver(guestContactSchema), defaultValues: contact });
  const heading = useRef<HTMLHeadingElement>(null);
  const top = useRef<HTMLDivElement>(null);

  const go = (next: Step) => {
    setStep(next);
    // Move focus to the new step's heading for screen readers and keyboard users, and bring the
    // stepper back into view (the previous step may have been scrolled far down on a phone).
    requestAnimationFrame(() => {
      top.current?.scrollIntoView({ block: "start" });
      heading.current?.focus({ preventScroll: true });
    });
  };

  const details: AttemptDetails | null =
    choice.doctorId !== null && choice.start !== null
      ? {
          doctor_id: choice.doctorId,
          starts_at: choice.start,
          contact_name: contact.contact_name.trim(),
          contact_phone: contact.contact_phone.trim(),
        }
      : null;

  const slotSummary =
    doctor && choice.start
      ? t("book.summary", {
          doctor: pick(doctor.name_ar, doctor.name_en),
          date: formatDate(choice.start, language, "long"),
          time: formatDate(choice.start, language, "time"),
        })
      : null;

  return (
    <div className="flex min-w-0 flex-col gap-5">
      <div ref={top} className="scroll-mt-20">
        <GuestStepper current={step} />
      </div>

      {step === "slot" ? (
        <StepLayout
          main={
            <>
              <SiteCard title={t("guest.steps.slot")} titleId="guest-step-title" titleRef={heading}>
                <SiteSlotChooser value={choice} onChange={setChoice} />
              </SiteCard>
              <ActionBar note={slotSummary ? <p className="truncate">{slotSummary}</p> : null}>
                <Button
                  size="lg"
                  className="w-full lg:ms-auto lg:w-auto"
                  disabled={!slotComplete(choice)}
                  data-testid="guest-next-contact"
                  onClick={() => {
                    go("contact");
                  }}
                >
                  {t("guest.next")}
                  <ChevronsNext />
                </Button>
              </ActionBar>
            </>
          }
          side={<ChoiceSummary choice={choice} />}
        />
      ) : null}

      {step === "contact" ? (
        <StepLayout
          main={
            <Form {...form}>
              <form
                noValidate
                className="flex flex-col gap-4"
                data-testid="guest-contact"
                onSubmit={(e) =>
                  void form.handleSubmit((values) => {
                    setContact(values);
                    go("review");
                  })(e)
                }
              >
                <SiteCard title={t("guest.steps.contact")} titleId="guest-step-title" titleRef={heading}>
                  <div className="grid gap-4 md:grid-cols-2">
                    <TextField
                      control={form.control}
                      name="contact_name"
                      label={t("guest.form.name")}
                      description={t("guest.form.nameHint")}
                      autoComplete="name"
                      maxLength={200}
                      required
                    />
                    <TextField
                      control={form.control}
                      name="contact_phone"
                      label={t("guest.form.phone")}
                      description={t("guest.form.phoneHint")}
                      type="tel"
                      inputMode="tel"
                      autoComplete="tel"
                      maxLength={30}
                      dir="ltr"
                      required
                    />
                  </div>
                </SiteCard>
                <ActionBar>
                  <BackButton
                    onClick={() => {
                      setContact(form.getValues());
                      go("slot");
                    }}
                  />
                  <Button
                    type="submit"
                    size="lg"
                    className="min-w-0 flex-1 lg:flex-none"
                    data-testid="guest-next-review"
                  >
                    {t("guest.next")}
                    <ChevronsNext />
                  </Button>
                </ActionBar>
              </form>
            </Form>
          }
          side={<ChoiceSummary choice={choice} />}
        />
      ) : null}

      {step === "review" && details ? (
        <StepLayout
          testId="guest-review-step"
          main={
            <>
              <SiteCard title={t("guest.steps.review")} titleId="guest-step-title" titleRef={heading}>
                <ReviewRows details={details} />
                <p className="text-sm text-pretty text-muted">{t("guest.reviewHint")}</p>
                <SendProgress state={state} />
                {error ? (
                  <AlertCard variant="danger" title={translateError(error)} live>
                    {retryable ? t("guest.retryHint") : null}
                  </AlertCard>
                ) : null}
              </SiteCard>
              <ActionBar>
                <BackButton
                  disabled={busy}
                  onClick={() => {
                    go("contact");
                  }}
                />
                <Button
                  size="lg"
                  className="min-w-0 flex-1 lg:flex-none"
                  loading={busy}
                  data-testid="guest-submit"
                  onClick={() => {
                    void send(attemptFor(details));
                  }}
                >
                  <CalendarCheck aria-hidden="true" />
                  {retryable ? t("guest.retry") : t("guest.submit")}
                </Button>
              </ActionBar>
            </>
          }
          side={<FeesAndPolicy />}
        />
      ) : null}
    </div>
  );
}

/** The reference and the PIN, shown once, with ways to keep them (ADR 0029 D, G). */
export function GuestConfirmation({ booking }: { booking: GuestBookingCreated }) {
  const { t } = useTranslation("portal");
  const pick = usePick();
  const detail = useDoctorDetail();
  const language = useLanguage();
  const requested = booking.status === "requested";
  const sub = detail(booking.doctor);
  // The reference and the PIN open at the top, whatever the review step's scroll was.
  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, []);
  return (
    <PortalPage
      title={requested ? t("guest.done.requestedTitle") : t("guest.done.bookedTitle")}
      description={requested ? t("guest.done.requestedText") : t("guest.done.bookedText")}
    >
      <GuestStepper current="done" />
      <StepLayout
        main={
          <>
            <section
              className="site-card flex flex-col gap-4 border-2 border-warning-border bg-warning-bg p-5 text-warning-fg lg:p-6"
              aria-labelledby="guest-save-title"
              data-testid="guest-confirmation"
            >
              <div className="flex items-start gap-3">
                <ShieldCheck aria-hidden="true" className="mt-0.5 size-6 shrink-0" />
                <div className="min-w-0">
                  <h2 id="guest-save-title" className="text-lg font-bold">
                    {t("guest.done.saveTitle")}
                  </h2>
                  <p className="text-sm text-pretty">{t("guest.done.saveText")}</p>
                </div>
              </div>
              <dl className="grid gap-3 sm:grid-cols-2">
                <div className="flex flex-col gap-1 rounded-card border border-border bg-surface p-4 text-fg">
                  <dt className="text-sm text-muted">{t("guest.reference")}</dt>
                  <dd className="num text-2xl font-bold tracking-wider lg:text-3xl" data-testid="guest-reference">
                    {booking.reference}
                  </dd>
                </div>
                <div className="flex flex-col gap-1 rounded-card border border-border bg-surface p-4 text-fg">
                  <dt className="text-sm text-muted">{t("guest.pin")}</dt>
                  {booking.pin ? (
                    <dd className="num text-2xl font-bold tracking-[0.3em] lg:text-3xl" data-testid="guest-pin">
                      {booking.pin}
                    </dd>
                  ) : (
                    <dd className="text-sm text-pretty" data-testid="guest-pin-missing">
                      {t("guest.done.pinMissing")}
                    </dd>
                  )}
                </div>
              </dl>
              <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap print:hidden">
                <Button asChild variant="outline" className="bg-surface">
                  <a href={booking.share_url} target="_blank" rel="noopener noreferrer" data-testid="guest-share">
                    <MessageCircle aria-hidden="true" />
                    {t("guest.done.share")}
                  </a>
                </Button>
                <Button
                  variant="outline"
                  className="bg-surface"
                  data-testid="guest-print"
                  onClick={() => {
                    window.print();
                  }}
                >
                  <Printer aria-hidden="true" />
                  {t("guest.done.print")}
                </Button>
              </div>
              <p className="text-xs text-pretty">{t("guest.done.shareHint")}</p>
            </section>

            <SiteCard title={t("guest.done.details")} titleId="guest-done-details">
              <dl className="divide-y divide-border">
                <Row label={t("guest.status")}>
                  <Pill tone={BOOKING_TONE[booking.display_status]} testId="guest-status">
                    {t(`appointments.display.${booking.display_status}`)}
                  </Pill>
                </Row>
                <Row label={t("book.doctor")}>
                  <span className="flex flex-col">
                    <span>{pick(booking.doctor.name_ar, booking.doctor.name_en)}</span>
                    {sub ? <span className="text-xs text-muted">{sub}</span> : null}
                  </span>
                </Row>
                <Row label={t("book.day")}>{formatDate(booking.starts_at, language, "long")}</Row>
                <Row label={t("book.time")}>
                  <bdi className="tabular">{formatDate(booking.starts_at, language, "time")}</bdi>
                </Row>
              </dl>
              {requested && booking.expires_at ? (
                <p className="text-sm text-pretty text-muted">
                  {t("appointments.awaitingHint", { time: formatDate(booking.expires_at, language, "datetime") })}
                </p>
              ) : null}
            </SiteCard>
          </>
        }
        side={
          <>
            <SiteCard title={t("guest.done.next")} titleId="guest-done-next" as="aside" className="print:hidden">
              <p className="text-sm text-pretty text-muted">{t("guest.done.nextText")}</p>
              <div className="flex flex-col gap-2">
                <Button asChild size="lg">
                  <Link to="/portal/booking" data-testid="guest-done-open">
                    <KeyRound aria-hidden="true" />
                    {t("guest.openBooking")}
                  </Link>
                </Button>
                <Button asChild size="lg" variant="outline">
                  <Link to="/portal">{t("login.centerLink")}</Link>
                </Button>
              </div>
            </SiteCard>
            <FeesAndPolicy />
          </>
        }
      />
    </PortalPage>
  );
}
