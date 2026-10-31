import { Link } from "@tanstack/react-router";
import { Check, KeyRound, LogIn } from "lucide-react";
import { type ReactNode, type Ref } from "react";
import { useTranslation } from "react-i18next";

import { ArrowBack } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { useCenterPage } from "@/lib/center/api";
import { formatDate } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";
import { getSiteConfig } from "@/lib/site";
import { cn } from "@/lib/utils";

import { useDoctors } from "../api";
import { GUEST_STEPS, stepNumber, stepState, type GuestStep, type SlotPick } from "../guest/steps";
import { formatDay, useDoctorDetail, usePick } from "../lib/ui";
import { Row } from "./PortalPage";

/** The website's larger card radius (`.site-card`), for surfaces that are not a `.site-card`. */
export const SITE_RADIUS = "rounded-[calc(var(--card-radius)+0.5rem)]";

/**
 * A soft website card (D-0022) with an optional heading; the guest booking pages' one surface
 * (D-0023). The heading can take focus, so a step change can move focus to it.
 */
export function SiteCard({
  title,
  titleId,
  titleRef,
  action,
  children,
  className,
  testId,
  as: Tag = "section",
}: {
  title?: ReactNode;
  titleId?: string;
  /** Given, the heading can take focus (a step change moves focus to it). */
  titleRef?: Ref<HTMLHeadingElement>;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  testId?: string;
  as?: "section" | "aside" | "div";
}) {
  return (
    <Tag
      className={cn("site-card flex min-w-0 flex-col gap-4 p-5 lg:p-6", className)}
      data-testid={testId}
      aria-labelledby={title && titleId ? titleId : undefined}
    >
      {title ? (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2
            ref={titleRef}
            id={titleId}
            tabIndex={titleRef ? -1 : undefined}
            className="rounded-control text-lg font-semibold text-balance text-fg focus-ring"
          >
            {title}
          </h2>
          {action}
        </div>
      ) : null}
      {children}
    </Tag>
  );
}

const STEP_COLUMNS: Record<number, string> = { 2: "grid-cols-2", 3: "grid-cols-3", 4: "grid-cols-4" };

/**
 * The booking steps, visible at every width (D-0023; reworked in D-0024 so labels never collide):
 * numbered marks joined by a line, one equal column per step. On phones only the marks show and
 * the open step's name with "Step x of n" sits on its own line under them (wrapping, never
 * clipped); from md every step is named under its mark and wraps inside its own column. The
 * other steps' names stay in the accessible name at every width.
 */
export function Stepper<S extends string>({
  steps,
  current,
  labelOf,
  testId,
}: {
  steps: readonly S[];
  current: S;
  labelOf: (step: S) => string;
  testId: string;
}) {
  const { t } = useTranslation("portal");
  return (
    <nav aria-label={t("guest.stepper.label")} data-testid={testId} className="print:hidden">
      <ol className={cn("grid min-w-0", STEP_COLUMNS[steps.length] ?? "auto-cols-fr grid-flow-col")}>
        {steps.map((step, index) => {
          const state = stepState(steps, step, current);
          const last = index === steps.length - 1;
          return (
            <li
              key={step}
              aria-current={state === "current" ? "step" : undefined}
              data-state={state}
              className="relative flex min-w-0 flex-col items-center gap-1.5 px-1 text-center"
            >
              {last ? null : (
                // From this mark's edge to the next mark's edge (marks are 2rem, 0.25rem apart).
                <span
                  aria-hidden="true"
                  className={cn(
                    "absolute start-[calc(50%+1.25rem)] top-4 h-px w-[calc(100%-2.5rem)]",
                    state === "done" ? "bg-primary" : "bg-border-strong",
                  )}
                />
              )}
              <span
                aria-hidden="true"
                data-step-mark=""
                className={cn(
                  "relative inline-flex size-8 shrink-0 items-center justify-center rounded-full border num text-sm font-semibold transition-colors",
                  state === "upcoming"
                    ? "border-border-strong bg-surface text-muted"
                    : "border-primary bg-primary text-primary-fg",
                  state === "current" && "shadow-card",
                )}
              >
                {state === "done" ? <Check className="size-4" /> : stepNumber(steps, step)}
              </span>
              <span
                data-step-label=""
                className={cn(
                  "max-w-full text-sm text-balance break-words max-md:sr-only",
                  state === "current" ? "font-semibold text-fg" : "text-muted",
                )}
              >
                {labelOf(step)}
                {state === "done" ? <span className="sr-only"> ({t("guest.stepper.done")})</span> : null}
              </span>
            </li>
          );
        })}
      </ol>
      <div
        className="mt-3 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 md:hidden"
        aria-hidden="true"
        data-testid={`${testId}-phone`}
      >
        <p className="min-w-0 text-sm font-semibold text-balance break-words text-fg" data-step-label="">
          {labelOf(current)}
        </p>
        <p className="text-xs text-muted" data-step-label="">
          {t("guest.step", { step: String(stepNumber(steps, current)), total: String(steps.length) })}
        </p>
      </div>
    </nav>
  );
}

/** The guest booking's four steps (D-0023). */
export function GuestStepper({ current }: { current: GuestStep }) {
  const { t } = useTranslation("portal");
  return (
    <Stepper steps={GUEST_STEPS} current={current} labelOf={(step) => t(`guest.steps.${step}`)} testId="guest-step" />
  );
}

/**
 * The step's actions. On phones and tablets a floating glass bar that stays in reach while the
 * step scrolls (sticky inside the step, so it never covers the footer); from lg a plain row.
 * In the signed-in portal (`aboveTabBar`) it floats above the phone tab bar (D-0024).
 */
export function ActionBar({
  children,
  note,
  aboveTabBar = false,
  testId = "guest-action-bar",
}: {
  children: ReactNode;
  note?: ReactNode;
  aboveTabBar?: boolean;
  testId?: string;
}) {
  return (
    <div
      className={cn(
        SITE_RADIUS,
        "site-glass sticky bottom-[calc(0.75rem+env(safe-area-inset-bottom))] z-10 flex flex-col gap-2 border border-border p-2 shadow-raised print:hidden",
        // The portal's phone tab bar is 3.5rem plus the safe area; from md it is a row at the top.
        aboveTabBar && "max-md:bottom-[calc(4.25rem+env(safe-area-inset-bottom))]",
        "lg:static lg:border-0 lg:bg-transparent lg:p-0 lg:shadow-none lg:backdrop-filter-none",
      )}
      data-testid={testId}
    >
      {note ? <div className="px-1 text-sm font-medium text-fg lg:hidden">{note}</div> : null}
      <div className="flex items-stretch gap-2 lg:justify-between">{children}</div>
    </div>
  );
}

/** The step's main column and, from lg, a sticky side column beside it (D-0023, D-0024). */
export function StepLayout({ main, side, testId }: { main: ReactNode; side: ReactNode; testId?: string }) {
  return (
    <div
      className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_20rem] lg:items-start lg:gap-8 xl:grid-cols-[minmax(0,1fr)_22rem]"
      data-testid={testId}
    >
      <div className="flex min-w-0 flex-col gap-4">{main}</div>
      <div className="flex min-w-0 flex-col gap-4 lg:sticky lg:top-20">{side}</div>
    </div>
  );
}

/** "Back" to the previous step, the action bar's secondary button. */
export function BackButton({ onClick, disabled }: { onClick: () => void; disabled?: boolean }) {
  const { t } = useTranslation("portal");
  return (
    <Button type="button" variant="outline" size="lg" className="flex-none px-4" disabled={disabled} onClick={onClick}>
      <ArrowBack className="size-4" />
      {t("guest.back")}
    </Button>
  );
}

/**
 * The side summary of the slot step (and the guest's details step): what is chosen so far, then
 * fees and the policy. `before` adds rows above the choice (the booking being moved).
 */
export function ChoiceSummary({ choice, before }: { choice: SlotPick; before?: ReactNode }) {
  const { t } = useTranslation("portal");
  const pick = usePick();
  const detail = useDoctorDetail();
  const language = useLanguage();
  const doctors = useDoctors();
  const doctor = doctors.data?.find((d) => d.id === choice.doctorId) ?? null;
  const sub = doctor ? detail(doctor) : "";
  return (
    <SiteCard title={t("guest.summary.title")} titleId="book-summary-title" as="aside" testId="book-summary">
      {before ? <dl className="divide-y divide-border">{before}</dl> : null}
      {doctor ? (
        <dl className="divide-y divide-border">
          <Row label={t("book.doctor")}>
            <span className="flex flex-col">
              <span className="font-semibold">{pick(doctor.name_ar, doctor.name_en)}</span>
              {sub ? <span className="text-xs text-muted">{sub}</span> : null}
            </span>
          </Row>
          {choice.day ? (
            <Row label={t("book.day")}>
              <bdi>{formatDay(choice.day, language)}</bdi>
            </Row>
          ) : null}
          {choice.start ? (
            <Row label={t("book.time")}>
              <bdi className="tabular">{formatDate(choice.start, language, "time")}</bdi>
            </Row>
          ) : null}
        </dl>
      ) : (
        <p className="text-sm text-pretty text-muted">{t("guest.summary.empty")}</p>
      )}
      <FeesAndPolicy />
    </SiteCard>
  );
}

/** "Fees are paid at reception" and the cancellation policy (ADR 0029 A5: no fees online). */
export function FeesAndPolicy({ className }: { className?: string }) {
  const { t } = useTranslation("portal");
  const pick = usePick();
  const center = useCenterPage();
  const policy = center.data ? pick(center.data.cancellation_policy_ar, center.data.cancellation_policy_en) : "";
  return (
    <div
      className={cn(
        "flex flex-col gap-2 rounded-card border border-info-border bg-info-bg p-4 text-info-fg",
        className,
      )}
      data-testid="guest-fees"
    >
      <p className="text-sm font-semibold">{t("center.fees.text")}</p>
      {policy ? (
        <div className="flex flex-col gap-1">
          <p className="text-sm font-semibold">{t("center.fees.cancellation")}</p>
          <p className="text-sm text-pretty whitespace-pre-line">{policy}</p>
        </div>
      ) : (
        <p className="text-sm text-pretty">{t("guest.policyDefault")}</p>
      )}
    </div>
  );
}

const entryLink =
  "inline-flex min-h-11 items-center gap-1.5 rounded-control font-medium text-primary-strong underline-offset-4 hover:underline focus-ring md:min-h-8";

/**
 * The other ways in, as one quiet line under the title: a patient with a file signs in (only
 * while patient sign-in is on), a visitor who booked before opens that booking.
 */
export function GuestEntryLinks() {
  const { t } = useTranslation("portal");
  const tracking = getSiteConfig().patientTracking;
  return (
    <nav
      aria-label={t("guest.entry.label")}
      className="flex flex-col gap-x-6 gap-y-0 text-sm text-muted sm:flex-row sm:flex-wrap sm:items-center print:hidden"
      data-testid="guest-entry-links"
    >
      {tracking ? (
        <p className="flex flex-wrap items-center gap-x-1.5">
          <span>{t("guest.patientHint")}</span>
          <Link to="/portal/sign-in" className={entryLink} data-testid="guest-patient-sign-in">
            <LogIn aria-hidden="true" className="size-4 rtl:-scale-x-100" />
            {t("guest.patientSignIn")}
          </Link>
        </p>
      ) : null}
      <p className="flex flex-wrap items-center gap-x-1.5">
        <span>{t("guest.bookedHint")}</span>
        <Link to="/portal/booking" className={entryLink} data-testid="guest-open-booking">
          <KeyRound aria-hidden="true" className="size-4" />
          {t("guest.openBooking")}
        </Link>
      </p>
    </nav>
  );
}
