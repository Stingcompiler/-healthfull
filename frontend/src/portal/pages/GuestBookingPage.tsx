import { zodResolver } from "@hookform/resolvers/zod";
import { Link } from "@tanstack/react-router";
import { CalendarClock, CalendarX, Clock, LogOut, Phone, Stethoscope } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { AlertCard } from "@/components/AlertCard";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Form, TextField } from "@/components/form";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { toApiError } from "@/lib/api/errors";
import { useTranslateError } from "@/lib/api/translate-error";
import { formatDate } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";
import { getSiteConfig } from "@/lib/site";

import { useCenterPage } from "@/lib/center/api";

import { FeesAndPolicy, SiteCard } from "../components/BookingParts";
import { Pill, PortalPage, Row } from "../components/PortalPage";
import { SiteSlotChooser, type SlotChoice } from "../components/SlotChooser";
import {
  forgetGuest,
  guestFlag,
  useGuestBooking,
  useGuestCancel,
  useGuestReschedule,
  useGuestSignIn,
  useGuestSignOut,
  type GuestBooking,
} from "../guest/api";
import { foldDigits, guestSignInSchema, normalizeReference, type GuestSignInValues } from "../guest/form";
import { BOOKING_TONE } from "../lib/tones";
import { useDoctorDetail, usePick } from "../lib/ui";

/**
 * `/portal/booking` (ADR 0029 D): a guest opens their one booking with its reference and PIN.
 * Every refusal reads the same (the server answers one uniform 401); the help text says that a
 * booking locks after wrong PINs and reception issues a new one. The view shows the
 * patient-facing status, time and doctor, and offers cancel and change of time within the rules
 * the server sends (`can_cancel`, `can_reschedule`). Layout (D-0023): from lg the form sits
 * beside a help card (where the reference and PIN are, a lost PIN, a new booking), and the
 * booking beside the fees and the policy, on the center website's soft cards.
 */
export function GuestBookingPage() {
  const { t } = useTranslation("portal");
  const [signedIn, setSignedIn] = useState(guestFlag);
  const booking = useGuestBooking(signedIn);
  // The server ended the session (idle, a new PIN, a switch): back to the sign-in form.
  const ended = signedIn && booking.isError && toApiError(booking.error).status === 401;

  useEffect(() => {
    if (ended) forgetGuest();
  }, [ended]);

  if (!signedIn || ended) {
    return (
      <GuestSignIn
        ended={ended}
        onSignedIn={() => {
          setSignedIn(true);
        }}
      />
    );
  }
  if (booking.isPending) {
    return (
      <PortalPage title={t("guest.view.title")}>
        <Skeleton className="h-48 rounded-card" />
      </PortalPage>
    );
  }
  if (booking.isError) {
    return (
      <PortalPage title={t("guest.view.title")}>
        <AlertCard variant="danger" title={t("guest.view.unavailable")} />
      </PortalPage>
    );
  }
  return (
    <GuestView
      booking={booking.data}
      onSignedOut={() => {
        setSignedIn(false);
      }}
    />
  );
}

/** Where the reference and the PIN are, what to do about a lost PIN, and a new booking. */
function SignInHelp() {
  const { t } = useTranslation("portal");
  const phone = useCenterPage().data?.phone_uri ?? "";
  const canBook = getSiteConfig().guestBooking;
  return (
    <SiteCard title={t("guest.signIn.helpTitle")} titleId="guest-help-title" as="aside" testId="guest-sign-in-help">
      <div className="flex flex-col divide-y divide-border">
        <div className="flex flex-col gap-1 pb-4">
          <h3 className="text-sm font-semibold text-fg">{t("guest.signIn.whereTitle")}</h3>
          <p className="text-sm text-pretty text-muted">{t("guest.signIn.whereText")}</p>
        </div>
        <div className="flex flex-col gap-2 py-4">
          <h3 className="text-sm font-semibold text-fg">{t("guest.signIn.forgotTitle")}</h3>
          <p className="text-sm text-pretty text-muted" data-testid="guest-forgot-pin">
            {t("guest.signIn.forgotText")}
          </p>
          {phone ? (
            <Button asChild variant="outline" className="w-fit">
              <a href={phone} data-testid="guest-call-reception">
                <Phone aria-hidden="true" />
                {t("guest.signIn.call")}
              </a>
            </Button>
          ) : null}
        </div>
        {canBook ? (
          <div className="flex flex-col gap-2 pt-4">
            <h3 className="text-sm font-semibold text-fg">{t("guest.signIn.newTitle")}</h3>
            <Button asChild variant="soft" className="w-fit">
              <Link to="/portal/book" data-testid="guest-book-new">
                {t("guest.signIn.bookNew")}
              </Link>
            </Button>
          </div>
        ) : null}
      </div>
    </SiteCard>
  );
}

function GuestSignIn({ ended, onSignedIn }: { ended: boolean; onSignedIn: () => void }) {
  const { t } = useTranslation(["portal", "errors"]);
  const translateError = useTranslateError();
  const signIn = useGuestSignIn();
  const form = useForm<GuestSignInValues>({
    resolver: zodResolver(guestSignInSchema),
    defaultValues: { reference: "", pin: "" },
  });
  const submit = form.handleSubmit(async (values) => {
    try {
      await signIn.mutateAsync({
        reference: normalizeReference(values.reference),
        pin: foldDigits(values.pin).replace(/[\s\-_.]/gu, ""),
      });
      onSignedIn();
    } catch {
      form.setValue("pin", "");
    }
  });
  const error = signIn.error ? toApiError(signIn.error) : null;
  return (
    <PortalPage
      title={t("guest.signIn.title")}
      description={t("guest.signIn.subtitle")}
      back={{ to: "/portal", label: t("login.centerLink") }}
    >
      <div className="grid gap-5 lg:grid-cols-2 lg:items-start lg:gap-8">
        <div className="site-card flex min-w-0 flex-col gap-4 p-5 lg:p-7">
          {ended && !error ? <AlertCard variant="info" title={t("guest.signIn.ended")} live /> : null}
          {error ? (
            <div data-testid="guest-sign-in-error">
              <AlertCard variant="danger" title={translateError(error)} live>
                {error.code === "GUEST_INVALID_CREDENTIALS" ? t("guest.signIn.lockedHint") : null}
              </AlertCard>
            </div>
          ) : null}
          <Form {...form}>
            <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4" data-testid="guest-sign-in">
              <TextField
                control={form.control}
                name="reference"
                label={t("guest.reference")}
                description={t("guest.signIn.referenceHint")}
                autoComplete="off"
                maxLength={20}
                dir="ltr"
                required
              />
              <TextField
                control={form.control}
                name="pin"
                label={t("guest.pin")}
                description={t("guest.signIn.pinHint")}
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={12}
                dir="ltr"
                required
              />
              <Button type="submit" size="lg" className="w-full" loading={form.formState.isSubmitting}>
                {t("guest.signIn.submit")}
              </Button>
            </form>
          </Form>
        </div>
        <SignInHelp />
      </div>
    </PortalPage>
  );
}

/** One way to change the booking: what it does and until when, then its button. */
function ActionRow({
  title,
  text,
  until,
  children,
}: {
  title: string;
  text: string;
  until?: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3 py-4 first:pt-0 last:pb-0 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex min-w-0 flex-col gap-0.5">
        <h3 className="text-sm font-semibold text-fg">{title}</h3>
        <p className="text-sm text-pretty text-muted">{text}</p>
        {until ? <p className="text-xs text-muted">{until}</p> : null}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

function GuestView({ booking, onSignedOut }: { booking: GuestBooking; onSignedOut: () => void }) {
  const { t } = useTranslation(["portal", "errors"]);
  const translateError = useTranslateError();
  const pick = usePick();
  const detail = useDoctorDetail();
  const language = useLanguage();
  const cancel = useGuestCancel();
  const signOut = useGuestSignOut();
  const [moving, setMoving] = useState(false);
  const requested = booking.status === "requested";
  const sub = detail(booking.doctor);
  return (
    <PortalPage
      title={t("guest.view.title")}
      actions={
        <Button
          variant="outline"
          size="sm"
          loading={signOut.isPending}
          data-testid="guest-sign-out"
          onClick={() => {
            void signOut.mutateAsync().finally(onSignedOut);
          }}
        >
          <LogOut aria-hidden="true" className="rtl:-scale-x-100" />
          {t("nav.signOut")}
        </Button>
      }
    >
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_20rem] lg:items-start lg:gap-8 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="flex min-w-0 flex-col gap-5">
          <section
            className="site-card flex min-w-0 flex-col gap-5 p-5 lg:p-7"
            aria-labelledby="guest-view-title"
            data-testid="guest-view"
          >
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 id="guest-view-title" className="flex flex-wrap items-baseline gap-x-2 text-sm text-muted">
                {t("guest.reference")}
                <bdi className="num text-base font-bold tracking-wider text-fg">{booking.reference}</bdi>
              </h2>
              <Pill tone={BOOKING_TONE[booking.display_status]} testId="guest-status">
                {t(`appointments.display.${booking.display_status}`)}
              </Pill>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="flex min-w-0 items-start gap-3">
                <Clock aria-hidden="true" className="mt-1 size-5 shrink-0 text-primary-strong" />
                <div className="flex min-w-0 flex-col">
                  <span className="text-xs text-muted">{t("guest.view.when")}</span>
                  <span className="text-lg font-semibold text-balance text-fg">
                    {formatDate(booking.starts_at, language, "long")}
                  </span>
                  <bdi className="tabular text-2xl font-bold text-fg" data-testid="guest-time">
                    {formatDate(booking.starts_at, language, "time")}
                  </bdi>
                </div>
              </div>
              <div className="flex min-w-0 items-start gap-3">
                <Stethoscope aria-hidden="true" className="mt-1 size-5 shrink-0 text-primary-strong" />
                <div className="flex min-w-0 flex-col">
                  <span className="text-xs text-muted">{t("book.doctor")}</span>
                  <span className="text-lg font-semibold break-words text-fg">
                    {pick(booking.doctor.name_ar, booking.doctor.name_en)}
                  </span>
                  {sub ? <span className="text-sm text-muted">{sub}</span> : null}
                </div>
              </div>
            </div>
            {requested && booking.expires_at ? (
              <p className="text-sm text-pretty text-muted" data-testid="guest-awaiting">
                {t("appointments.awaitingHint", { time: formatDate(booking.expires_at, language, "datetime") })}
              </p>
            ) : null}
            <dl className="divide-y divide-border border-t border-border pt-2">
              <Row label={t("guest.form.name")}>{booking.contact_name}</Row>
              <Row label={t("guest.form.phone")}>
                <bdi className="num">{booking.phone_masked}</bdi>
              </Row>
            </dl>
          </section>

          {moving ? (
            <GuestReschedule
              booking={booking}
              onDone={() => {
                setMoving(false);
              }}
            />
          ) : (
            <SiteCard title={t("guest.view.actions")} titleId="guest-actions-title">
              {cancel.isError ? <AlertCard variant="danger" title={translateError(cancel.error)} live /> : null}
              {booking.can_reschedule || booking.can_cancel ? (
                <div className="flex flex-col divide-y divide-border">
                  {booking.can_reschedule ? (
                    <ActionRow
                      title={t("appointments.reschedule")}
                      text={t("guest.view.rescheduleText")}
                      until={
                        booking.reschedule_until
                          ? t("appointments.rescheduleUntil", {
                              time: formatDate(booking.reschedule_until, language, "datetime"),
                            })
                          : undefined
                      }
                    >
                      <Button
                        variant="outline"
                        data-testid="guest-reschedule"
                        onClick={() => {
                          setMoving(true);
                        }}
                      >
                        <CalendarClock aria-hidden="true" />
                        {t("appointments.reschedule")}
                      </Button>
                    </ActionRow>
                  ) : null}
                  {booking.can_cancel ? (
                    <ActionRow
                      title={t("appointments.cancel")}
                      text={t("guest.view.cancelText")}
                      until={
                        booking.cancel_until
                          ? t("appointments.cancelUntil", {
                              time: formatDate(booking.cancel_until, language, "datetime"),
                            })
                          : undefined
                      }
                    >
                      <ConfirmDialog
                        trigger={
                          <Button variant="destructive-soft" data-testid="guest-cancel">
                            <CalendarX aria-hidden="true" />
                            {t("appointments.cancel")}
                          </Button>
                        }
                        title={t("appointments.cancelTitle")}
                        description={t("appointments.cancelDescription")}
                        confirmLabel={t("appointments.cancelConfirm")}
                        cancelLabel={t("appointments.keep")}
                        destructive
                        onConfirm={async () => {
                          await cancel.mutateAsync();
                          toast.success(t("appointments.cancelled"));
                        }}
                      />
                    </ActionRow>
                  ) : null}
                </div>
              ) : (
                <p className="text-sm text-pretty text-muted" data-testid="guest-no-actions">
                  {t("guest.view.noActions")}
                </p>
              )}
            </SiteCard>
          )}
        </div>
        <div className="flex min-w-0 flex-col gap-5 lg:sticky lg:top-20">
          <FeesAndPolicy />
        </div>
      </div>
    </PortalPage>
  );
}

function GuestReschedule({ booking, onDone }: { booking: GuestBooking; onDone: () => void }) {
  const { t } = useTranslation(["portal", "errors"]);
  const translateError = useTranslateError();
  const language = useLanguage();
  const move = useGuestReschedule();
  const [choice, setChoice] = useState<SlotChoice>({ doctorId: booking.doctor.id, day: null, start: null });
  return (
    <SiteCard title={t("book.rescheduleTitle")} titleId="guest-move-title" testId="guest-reschedule-picker">
      <p className="text-sm text-pretty text-muted">
        {t("book.rescheduleDescription", {
          date: formatDate(booking.starts_at, language, "long"),
          time: formatDate(booking.starts_at, language, "time"),
        })}
      </p>
      <SiteSlotChooser value={choice} onChange={setChoice} />
      {move.isError ? <AlertCard variant="danger" title={translateError(move.error)} live /> : null}
      <div className="flex flex-col-reverse gap-2 border-t border-border pt-4 sm:flex-row sm:justify-between">
        <Button variant="outline" size="lg" onClick={onDone} disabled={move.isPending}>
          {t("guest.back")}
        </Button>
        <Button
          size="lg"
          disabled={choice.doctorId === null || choice.start === null}
          loading={move.isPending}
          data-testid="guest-reschedule-confirm"
          onClick={() => {
            if (choice.doctorId === null || choice.start === null) return;
            void move
              .mutateAsync({ doctor_id: choice.doctorId, starts_at: choice.start })
              .then((saved) => {
                toast.success(saved.status === "requested" ? t("book.requested") : t("book.moved"));
                onDone();
              })
              .catch(() => undefined);
          }}
        >
          {t("book.confirmMove")}
        </Button>
      </div>
    </SiteCard>
  );
}
