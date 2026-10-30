import { zodResolver } from "@hookform/resolvers/zod";
import { Link } from "@tanstack/react-router";
import { CalendarClock, LogOut } from "lucide-react";
import { useEffect, useState } from "react";
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

import { Pill, PortalPage, PortalSection, Row } from "../components/PortalPage";
import { SlotChooser, type SlotChoice } from "../components/SlotChooser";
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
import { usePick } from "../lib/ui";
import { FeesAndPolicy } from "./GuestBookPage";

/**
 * `/portal/booking` (ADR 0029 D): a guest opens their one booking with its reference and PIN.
 * Every refusal reads the same (the server answers one uniform 401); the help text says that a
 * booking locks after wrong PINs and reception issues a new one. The view shows the
 * patient-facing status, time and doctor, and offers cancel and change of time within the rules
 * the server sends (`can_cancel`, `can_reschedule`).
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
        <Skeleton className="h-48" />
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
      <div className="card-surface grid gap-4 p-(--d-card-pad)">
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
      <p className="text-sm text-pretty text-muted">{t("guest.signIn.help")}</p>
      {getSiteConfig().guestBooking ? (
        <Button asChild variant="link" className="w-fit px-0">
          <Link to="/portal/book">{t("guest.signIn.bookNew")}</Link>
        </Button>
      ) : null}
    </PortalPage>
  );
}

function GuestView({ booking, onSignedOut }: { booking: GuestBooking; onSignedOut: () => void }) {
  const { t } = useTranslation(["portal", "errors"]);
  const translateError = useTranslateError();
  const pick = usePick();
  const language = useLanguage();
  const cancel = useGuestCancel();
  const signOut = useGuestSignOut();
  const [moving, setMoving] = useState(false);
  const requested = booking.status === "requested";
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
      <PortalSection
        title={
          <span className="flex flex-wrap items-center gap-2">
            {t("guest.reference")} <bdi className="num">{booking.reference}</bdi>
          </span>
        }
        testId="guest-view"
      >
        <dl className="divide-y divide-border">
          <Row label={t("guest.status")}>
            <Pill tone={BOOKING_TONE[booking.display_status]} testId="guest-status">
              {t(`appointments.display.${booking.display_status}`)}
            </Pill>
          </Row>
          <Row label={t("book.doctor")}>{pick(booking.doctor.name_ar, booking.doctor.name_en)}</Row>
          <Row label={t("book.day")}>{formatDate(booking.starts_at, language, "long")}</Row>
          <Row label={t("book.time")}>
            <bdi className="tabular" data-testid="guest-time">
              {formatDate(booking.starts_at, language, "time")}
            </bdi>
          </Row>
          <Row label={t("guest.form.name")}>{booking.contact_name}</Row>
          <Row label={t("guest.form.phone")}>
            <bdi className="num">{booking.phone_masked}</bdi>
          </Row>
        </dl>
        {requested && booking.expires_at ? (
          <p className="text-sm text-pretty text-muted" data-testid="guest-awaiting">
            {t("appointments.awaitingHint", { time: formatDate(booking.expires_at, language, "datetime") })}
          </p>
        ) : null}
      </PortalSection>

      {moving ? (
        <GuestReschedule
          booking={booking}
          onDone={() => {
            setMoving(false);
          }}
        />
      ) : (
        <PortalSection title={t("guest.view.actions")}>
          {cancel.isError ? <AlertCard variant="danger" title={translateError(cancel.error)} live /> : null}
          {booking.can_reschedule ? (
            <div className="flex flex-wrap items-center justify-between gap-2">
              {booking.reschedule_until ? (
                <p className="text-sm text-muted">
                  {t("appointments.rescheduleUntil", {
                    time: formatDate(booking.reschedule_until, language, "datetime"),
                  })}
                </p>
              ) : null}
              <Button
                variant="outline"
                size="sm"
                data-testid="guest-reschedule"
                onClick={() => {
                  setMoving(true);
                }}
              >
                <CalendarClock aria-hidden="true" />
                {t("appointments.reschedule")}
              </Button>
            </div>
          ) : null}
          {booking.can_cancel ? (
            <div className="flex flex-wrap items-center justify-between gap-2">
              {booking.cancel_until ? (
                <p className="text-sm text-muted">
                  {t("appointments.cancelUntil", { time: formatDate(booking.cancel_until, language, "datetime") })}
                </p>
              ) : null}
              <ConfirmDialog
                trigger={
                  <Button variant="destructive-soft" size="sm" data-testid="guest-cancel">
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
            </div>
          ) : null}
          {!booking.can_cancel && !booking.can_reschedule ? (
            <p className="text-sm text-pretty text-muted" data-testid="guest-no-actions">
              {t("guest.view.noActions")}
            </p>
          ) : null}
        </PortalSection>
      )}

      <FeesAndPolicy />
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
    <div className="flex flex-col gap-5" data-testid="guest-reschedule-picker">
      <p className="text-sm text-pretty text-muted">
        {t("book.rescheduleDescription", {
          date: formatDate(booking.starts_at, language, "long"),
          time: formatDate(booking.starts_at, language, "time"),
        })}
      </p>
      <SlotChooser value={choice} onChange={setChoice} />
      {move.isError ? <AlertCard variant="danger" title={translateError(move.error)} live /> : null}
      <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-between">
        <Button variant="outline" onClick={onDone} disabled={move.isPending}>
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
    </div>
  );
}
