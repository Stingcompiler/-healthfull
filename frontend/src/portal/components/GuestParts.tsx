import { Link } from "@tanstack/react-router";
import { Check, KeyRound, LogIn } from "lucide-react";
import { type ReactNode, type Ref } from "react";
import { useTranslation } from "react-i18next";

import { useCenterPage } from "@/lib/center/api";
import { getSiteConfig } from "@/lib/site";
import { cn } from "@/lib/utils";

import { GUEST_STEPS, stepNumber, stepState, type GuestStep } from "../guest/steps";
import { usePick } from "../lib/ui";

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

/**
 * The booking steps, visible at every width: numbered marks joined by a line, the open step
 * named (on phones only the open one, the others stay in the accessible name).
 */
export function GuestStepper({ current }: { current: GuestStep }) {
  const { t } = useTranslation("portal");
  return (
    <nav aria-label={t("guest.stepper.label")} data-testid="guest-step" className="print:hidden">
      <ol className="flex min-w-0 items-center gap-2">
        {GUEST_STEPS.map((step, index) => {
          const state = stepState(step, current);
          const last = index === GUEST_STEPS.length - 1;
          return (
            <li
              key={step}
              aria-current={state === "current" ? "step" : undefined}
              data-state={state}
              className={cn("flex min-w-0 items-center gap-2", last ? "flex-none" : "flex-1")}
            >
              <span
                aria-hidden="true"
                className={cn(
                  "inline-flex size-8 shrink-0 items-center justify-center rounded-full border num text-sm font-semibold transition-colors",
                  state === "upcoming"
                    ? "border-border-strong bg-surface text-muted"
                    : "border-primary bg-primary text-primary-fg",
                  state === "current" && "shadow-card",
                )}
              >
                {state === "done" ? <Check className="size-4" /> : stepNumber(step)}
              </span>
              <span
                className={cn(
                  "min-w-0 text-sm",
                  state === "current" ? "font-semibold whitespace-nowrap text-fg" : "text-muted max-md:sr-only",
                )}
              >
                {t(`guest.steps.${step}`)}
                {state === "done" ? <span className="sr-only"> ({t("guest.stepper.done")})</span> : null}
              </span>
              {last ? null : (
                <span
                  aria-hidden="true"
                  className={cn("h-px min-w-3 flex-1", state === "done" ? "bg-primary" : "bg-border-strong")}
                />
              )}
            </li>
          );
        })}
      </ol>
      <p className="mt-1.5 text-xs text-muted md:hidden" aria-hidden="true">
        {t("guest.step", { step: String(stepNumber(current)), total: String(GUEST_STEPS.length) })}
      </p>
    </nav>
  );
}

/**
 * The step's actions. On phones and tablets a floating glass bar that stays in reach while the
 * step scrolls (sticky inside the step, so it never covers the footer); from lg a plain row.
 */
export function ActionBar({ children, note }: { children: ReactNode; note?: ReactNode }) {
  return (
    <div
      className={cn(
        SITE_RADIUS,
        "site-glass sticky bottom-[calc(0.75rem+env(safe-area-inset-bottom))] z-10 flex flex-col gap-2 border border-border p-2 shadow-raised print:hidden",
        "lg:static lg:border-0 lg:bg-transparent lg:p-0 lg:shadow-none lg:backdrop-filter-none",
      )}
      data-testid="guest-action-bar"
    >
      {note ? <div className="px-1 text-sm font-medium text-fg lg:hidden">{note}</div> : null}
      <div className="flex items-stretch gap-2 lg:justify-between">{children}</div>
    </div>
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
