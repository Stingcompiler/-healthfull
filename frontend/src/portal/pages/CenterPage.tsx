import { Link } from "@tanstack/react-router";
import { Mail, MapPin, MessageCircle, Phone } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { CenterLogo } from "@/components/CenterIdentity";
import { DateText } from "@/components/DateText";
import { ChevronNext } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";
import { useCenterPage, type CenterPage as CenterPageData, type CenterToday } from "@/lib/center/api";
import { useCenterName, useTodayText } from "@/lib/center/hooks";
import { useDocumentTitle } from "@/lib/hooks/use-document-title";
import { useLanguage } from "@/lib/i18n-hooks";
import { formatClock, groupClinicDays, WEEK_ORDER, weekdayName } from "@/lib/weekdays";
import { cn } from "@/lib/utils";

import { usePortalMe } from "../api";
import { Pill, PortalSection } from "../components/PortalPage";
import { usePick } from "../lib/ui";

/** The one action of the page, repeated at the top and the end (LANDING section 2). */
function SignInAction({ className }: { className?: string }) {
  const { t } = useTranslation("portal");
  const me = usePortalMe();
  const signedIn = Boolean(me.data);
  return (
    <Button asChild size="lg" className={cn("w-full sm:w-auto", className)}>
      <Link to={signedIn ? "/portal/home" : "/portal/sign-in"} data-testid="center-sign-in">
        {signedIn ? t("center.openFile") : t("center.signIn")}
        <ChevronNext className="size-4" aria-hidden="true" />
      </Link>
    </Button>
  );
}

function TodayStatus({ today }: { today: CenterToday }) {
  const text = useTodayText(today);
  return (
    <Pill tone={today.state === "open" ? "success" : "neutral"} testId="center-today">
      {text}
    </Pill>
  );
}

function Hours({ page }: { page: CenterPageData }) {
  const { t } = useTranslation("portal");
  const language = useLanguage();
  const byDay = new Map(page.hours.map((h) => [h.weekday, h]));
  return (
    <PortalSection title={t("center.hours")} testId="center-hours">
      <dl className="divide-y divide-border">
        {WEEK_ORDER.map((weekday) => {
          const day = byDay.get(weekday);
          if (!day) return null;
          const isToday = page.today?.weekday === weekday;
          return (
            <div
              key={weekday}
              className={cn("flex items-baseline justify-between gap-3 py-2 text-sm", isToday && "font-semibold")}
              aria-current={isToday ? "date" : undefined}
            >
              <dt className="text-fg">
                {weekdayName(weekday, language)}
                {isToday ? <span className="ms-2 text-xs font-normal text-muted">{t("center.todayLabel")}</span> : null}
              </dt>
              <dd className={day.closed ? "text-muted" : "tabular text-fg"}>
                {day.closed || !day.opens || !day.closes
                  ? t("center.closed")
                  : t("center.span", { from: formatClock(day.opens, language), to: formatClock(day.closes, language) })}
              </dd>
            </div>
          );
        })}
      </dl>
    </PortalSection>
  );
}

function Doctors({ page }: { page: CenterPageData }) {
  const { t } = useTranslation("portal");
  const language = useLanguage();
  const pick = usePick();
  return (
    <PortalSection title={t("center.doctors")} testId="center-doctors">
      <ul className="divide-y divide-border">
        {page.doctors.map((doctor) => (
          <li key={doctor.id} className="flex flex-col gap-1 py-3 first:pt-0 last:pb-0" data-testid="center-doctor">
            <p className="text-sm font-semibold text-fg">{pick(doctor.name_ar, doctor.name_en)}</p>
            <p className="text-xs text-muted">
              {[
                ...new Set(
                  [
                    pick(doctor.specialty_ar, doctor.specialty_en),
                    pick(doctor.department_ar, doctor.department_en),
                  ].filter(Boolean),
                ),
              ].join(" · ")}
            </p>
            <ul className="mt-1 flex flex-col gap-0.5 text-sm text-fg">
              {groupClinicDays(doctor.clinic_days).map((group) => (
                <li key={group.weekdays.join("-")} className="flex flex-wrap gap-x-2">
                  <span>{group.weekdays.map((d) => weekdayName(d, language, "short")).join(t("center.listJoin"))}</span>
                  <span className="tabular text-muted">
                    {group.spans
                      .map((s) =>
                        t("center.span", { from: formatClock(s.starts, language), to: formatClock(s.ends, language) }),
                      )
                      .join(t("center.listJoin"))}
                  </span>
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </PortalSection>
  );
}

function ContactRow({ icon, children }: { icon: ReactNode; children: ReactNode }) {
  return (
    <li className="flex min-h-11 items-center gap-3">
      <span className="shrink-0 text-muted">{icon}</span>
      <span className="min-w-0 text-sm break-words text-fg">{children}</span>
    </li>
  );
}

const linkClass =
  "inline-flex min-h-11 items-center font-medium text-primary-strong underline-offset-4 hover:underline";

function Contact({ page }: { page: CenterPageData }) {
  const { t } = useTranslation("portal");
  const pick = usePick();
  const directions = pick(page.directions_ar, page.directions_en);
  const hasContact = Boolean(page.phone_uri || page.whatsapp || page.email);
  const hasAddress = Boolean(page.address || directions);
  if (!hasContact && !hasAddress) return null;
  return (
    <PortalSection title={t("center.contact")} testId="center-contact">
      <ul className="flex flex-col">
        {page.phone_uri ? (
          <ContactRow icon={<Phone className="size-4" aria-hidden="true" />}>
            <a href={page.phone_uri} className={linkClass} data-testid="center-phone">
              <span className="sr-only">{t("center.call")} </span>
              <span className="num">{page.phone}</span>
            </a>
          </ContactRow>
        ) : null}
        {page.whatsapp ? (
          <ContactRow icon={<MessageCircle className="size-4" aria-hidden="true" />}>
            <a href={`https://wa.me/${page.whatsapp}`} className={cn(linkClass, "gap-2")} data-testid="center-whatsapp">
              {t("center.whatsapp")}
              <span className="num font-normal text-muted">+{page.whatsapp}</span>
            </a>
          </ContactRow>
        ) : null}
        {page.email ? (
          <ContactRow icon={<Mail className="size-4" aria-hidden="true" />}>
            <a href={`mailto:${page.email}`} className={linkClass} dir="ltr">
              {page.email}
            </a>
          </ContactRow>
        ) : null}
        {hasAddress ? (
          <ContactRow icon={<MapPin className="size-4" aria-hidden="true" />}>
            <span className="block py-2">
              {page.address ? <span className="block">{page.address}</span> : null}
              {directions ? <span className="block text-muted">{directions}</span> : null}
            </span>
          </ContactRow>
        ) : null}
      </ul>
    </PortalSection>
  );
}

/**
 * The center page at the portal's door (before sign-in): who the center is, when it is open,
 * its doctors and clinic days, notices and how to reach it, and one action: sign in to one's
 * file. Every section comes from the center's settings and existing data; an empty or hidden
 * section is left out, never shown as a placeholder.
 */
export function CenterPage() {
  const { t } = useTranslation(["portal", "errors"]);
  const translateError = useTranslateError();
  const pick = usePick();
  const name = useCenterName();
  const center = useCenterPage();
  useDocumentTitle(name);
  const page = center.data;
  const about = page ? pick(page.about_ar, page.about_en) : "";

  return (
    <div className="flex min-w-0 flex-col gap-5" data-testid="center-page">
      <section className="flex flex-col gap-4 pt-1" aria-labelledby="center-name">
        <div className="flex items-center gap-3">
          <CenterLogo size="lg" />
          <div className="min-w-0">
            <h1 id="center-name" className="text-2xl font-bold text-balance text-fg">
              {name}
            </h1>
            {page?.today ? (
              <div className="mt-1">
                <TodayStatus today={page.today} />
              </div>
            ) : null}
          </div>
        </div>
        {about ? <p className="text-base text-pretty text-fg">{about}</p> : null}
        <div className="flex flex-col gap-2">
          <SignInAction />
          <p className="text-sm text-pretty text-muted">{t("center.signInHint")}</p>
        </div>
      </section>

      {center.isPending ? (
        <div className="grid gap-3">
          <Skeleton className="h-32" />
          <Skeleton className="h-48" />
        </div>
      ) : center.isError ? (
        <AlertCard variant="warning" title={t("center.unavailable")}>
          {translateError(center.error)}
        </AlertCard>
      ) : page ? (
        <>
          {page.announcements.length > 0 ? (
            <PortalSection title={t("center.announcements")} testId="center-announcements">
              <ul className="divide-y divide-border">
                {page.announcements.map((a) => {
                  const body = pick(a.body_ar, a.body_en);
                  return (
                    <li
                      key={a.id}
                      className="flex flex-col gap-1 py-3 first:pt-0 last:pb-0"
                      data-testid="center-announcement"
                    >
                      <p className="text-sm font-semibold text-fg">{pick(a.title_ar, a.title_en)}</p>
                      {body ? <p className="text-sm text-pretty whitespace-pre-line text-fg">{body}</p> : null}
                      {a.ends_on ? (
                        <p className="text-xs text-muted">
                          {t("center.until")} <DateText value={a.ends_on} />
                        </p>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            </PortalSection>
          ) : null}
          <div className="grid gap-5 md:grid-cols-2 md:items-start">
            {page.hours.length > 0 ? <Hours page={page} /> : null}
            <Contact page={page} />
          </div>
          {page.doctors.length > 0 ? <Doctors page={page} /> : null}
          {page.departments.length > 0 ? (
            <PortalSection title={t("center.departments")} testId="center-departments">
              <ul className="flex flex-wrap gap-2">
                {page.departments.map((d) => (
                  <li key={d.id} className="rounded-full border border-border px-3 py-1 text-sm text-fg">
                    {pick(d.name_ar, d.name_en)}
                  </li>
                ))}
              </ul>
            </PortalSection>
          ) : null}
          <div className="flex flex-col gap-2 border-t border-border pt-5">
            <p className="text-sm text-pretty text-fg">{t("center.endPrompt")}</p>
            <SignInAction />
          </div>
        </>
      ) : null}
    </div>
  );
}
