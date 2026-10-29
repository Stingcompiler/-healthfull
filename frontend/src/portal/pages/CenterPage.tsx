import { Link } from "@tanstack/react-router";
import { CalendarPlus, Check, ExternalLink, Mail, MapPin, MessageCircle, Phone } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { DateText } from "@/components/DateText";
import { ChevronNext } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";
import {
  useCenterPage,
  type CenterDoctor,
  type CenterImage,
  type CenterPage as CenterPageData,
} from "@/lib/center/api";
import { useCenterName, useOpenStatusText } from "@/lib/center/hooks";
import { useDocumentTitle } from "@/lib/hooks/use-document-title";
import { useLanguage } from "@/lib/i18n-hooks";
import { initialsOf } from "@/lib/initials";
import { cn } from "@/lib/utils";
import { getSiteConfig } from "@/lib/site";
import { formatClock, groupClinicDays, WEEK_ORDER, weekdayName } from "@/lib/weekdays";

import { usePortalMe } from "../api";
import { Pill } from "../components/PortalPage";
import { usePick } from "../lib/ui";

const ADDRESS_ID = "center-address";

/** Scrolls to the address card (the "directions" action: no map is fetched from outside). */
function goToAddress() {
  const target = document.getElementById(ADDRESS_ID);
  if (!target) return;
  const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  target.scrollIntoView({ behavior: calm ? "auto" : "smooth", block: "center" });
}

/** The one action of the page, repeated in the hero, after the content and in the phone bar. */
function SignInAction({ className, testId = "center-sign-in" }: { className?: string; testId?: string }) {
  const { t } = useTranslation("portal");
  const me = usePortalMe();
  const signedIn = Boolean(me.data);
  return (
    <Button asChild size="lg" className={cn("w-full sm:w-auto", className)}>
      <Link to={signedIn ? "/portal/home" : "/portal/sign-in"} data-testid={testId}>
        {signedIn ? t("center.openFile") : t("center.signIn")}
        <ChevronNext className="size-4" aria-hidden="true" />
      </Link>
    </Button>
  );
}

/** The center's logo when one is set (and loads), else a monogram of its name. */
function CenterMark({ page, name }: { page: CenterPageData | undefined; name: string }) {
  const [broken, setBroken] = useState(false);
  const logo = broken ? null : (page?.logo_url ?? null);
  const box = "size-16 lg:size-20";
  if (logo) {
    return (
      <img
        src={logo}
        alt=""
        width={80}
        height={80}
        className={cn(box, "shrink-0 rounded-card bg-surface object-contain p-1.5")}
        onError={() => {
          setBroken(true);
        }}
      />
    );
  }
  return (
    <span
      aria-hidden="true"
      data-testid="center-monogram"
      className={cn(
        box,
        "inline-flex shrink-0 items-center justify-center rounded-card bg-primary text-2xl font-bold text-primary-fg lg:text-3xl",
      )}
    >
      {initialsOf(name) || "+"}
    </span>
  );
}

function StatusChip({ page }: { page: CenterPageData }) {
  const text = useOpenStatusText(page.today, page.hours);
  if (!page.today || !text) return null;
  const open = page.today.state === "open";
  return (
    <Pill tone={open ? "success" : "neutral"} testId="center-today">
      <span aria-hidden="true" className="me-1.5 size-1.5 rounded-full bg-current" />
      {text}
    </Pill>
  );
}

/**
 * The single identity block: logo or monogram, name, today's status, a short about line and the
 * one action. Tinted with the theme's soft brand surface (no gradient: ui-profile).
 */
/** An image the center uploaded, with its size reserved so nothing jumps while it loads. */
function SiteImage({
  image,
  className,
  eager,
  alt,
}: {
  image: CenterImage;
  className?: string;
  eager?: boolean;
  alt?: string;
}) {
  const pick = usePick();
  const [broken, setBroken] = useState(false);
  if (broken) return null;
  return (
    <img
      src={image.url}
      alt={alt ?? pick(image.alt_ar, image.alt_en)}
      width={image.width}
      height={image.height}
      loading={eager ? "eager" : "lazy"}
      decoding="async"
      className={cn("bg-subtle object-cover", className)}
      onError={() => {
        setBroken(true);
      }}
    />
  );
}

/**
 * The single identity block: logo or monogram, name, today's status, the center's opening words
 * and the one action, with the hero image beside it on large screens. Tinted with the theme's
 * soft brand surface (no gradient: ui-profile).
 */
function Hero({ page, name }: { page: CenterPageData | undefined; name: string }) {
  const { t } = useTranslation("portal");
  const pick = usePick();
  const title = page ? pick(page.hero_title_ar, page.hero_title_en) : "";
  const text = page ? pick(page.hero_text_ar, page.hero_text_en) : "";
  const image = page?.hero_image ?? null;
  return (
    <section
      className="overflow-hidden rounded-card border border-border bg-primary-soft"
      aria-labelledby="center-name"
      data-testid="center-hero"
    >
      <div
        className={cn(
          "grid",
          image && "lg:grid-cols-[minmax(0,1fr)_minmax(0,26rem)] xl:grid-cols-[minmax(0,1fr)_30rem]",
        )}
      >
        <div className="flex min-w-0 flex-col gap-6 p-5 sm:p-6 lg:justify-center lg:p-10">
          <div className="flex min-w-0 flex-col gap-4">
            <div className="flex items-center gap-4">
              <CenterMark page={page} name={name} />
              <h1
                id="center-name"
                className="min-w-0 text-[1.75rem] leading-tight font-bold text-balance break-words text-fg sm:text-4xl lg:text-[2.5rem]"
              >
                {name}
              </h1>
            </div>
            {page ? <StatusChip page={page} /> : null}
            {title ? (
              <p className="text-lg font-semibold text-balance text-fg lg:text-xl" data-testid="center-hero-title">
                {title}
              </p>
            ) : null}
            {text ? <p className="text-base text-pretty text-fg lg:text-lg">{text}</p> : null}
          </div>
          {getSiteConfig().patientTracking ? (
            <div className="flex flex-col gap-2 sm:max-w-sm">
              <SignInAction />
              <p className="text-sm text-pretty text-muted">{t("center.signInHint")}</p>
            </div>
          ) : null}
        </div>
        {image ? <SiteImage image={image} eager className="aspect-[4/3] h-full max-h-80 w-full lg:max-h-none" /> : null}
      </div>
    </section>
  );
}

const actionClass = "h-auto min-h-11 flex-col gap-0.5 py-2 whitespace-normal md:flex-row md:gap-2";

/** Call, WhatsApp, directions and booking right under the hero on phones and tablets. */
function QuickActions({ page }: { page: CenterPageData }) {
  const { t } = useTranslation("portal");
  const pick = usePick();
  const me = usePortalMe();
  const signedIn = Boolean(me.data);
  const hasAddress = Boolean(page.address || pick(page.directions_ar, page.directions_en) || page.maps_url);
  const items: ReactNode[] = [];
  if (page.phone_uri) {
    items.push(
      <Button key="call" asChild variant="outline" className={actionClass}>
        <a href={page.phone_uri} data-testid="quick-call">
          <Phone aria-hidden="true" />
          {t("center.call")}
        </a>
      </Button>,
    );
  }
  if (page.whatsapp) {
    items.push(
      <Button key="wa" asChild variant="outline" className={actionClass}>
        <a href={`https://wa.me/${page.whatsapp}`} rel="noopener noreferrer" data-testid="quick-whatsapp">
          <MessageCircle aria-hidden="true" />
          {t("center.whatsapp")}
        </a>
      </Button>,
    );
  }
  if (hasAddress) {
    items.push(
      <Button key="dir" variant="outline" className={actionClass} onClick={goToAddress} data-testid="quick-directions">
        <MapPin aria-hidden="true" />
        {t("center.quick.directions")}
      </Button>,
    );
  }
  // Booking needs a patient session today, so both switches must be on (ADR 0029).
  const { onlineBooking, patientTracking } = getSiteConfig();
  if (page.doctors.length > 0 && onlineBooking && patientTracking) {
    items.push(
      <Button key="book" asChild variant="outline" className={actionClass}>
        <Link to={signedIn ? "/portal/appointments/new" : "/portal/sign-in"} data-testid="quick-book">
          <span className="flex items-center gap-2">
            <CalendarPlus aria-hidden="true" />
            {t("center.quick.book")}
          </span>
          {signedIn ? null : <span className="text-xs font-normal text-muted">{t("center.bookHint")}</span>}
        </Link>
      </Button>,
    );
  }
  if (items.length === 0) return null;
  return (
    <nav
      aria-label={t("center.quick.label")}
      className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:hidden [&>*:last-child:nth-child(odd)]:col-span-2 sm:[&>*:last-child:nth-child(odd)]:col-span-1"
      data-testid="center-quick-actions"
    >
      {items}
    </nav>
  );
}

function SectionTitle({ children }: { children: ReactNode }) {
  return <h2 className="text-lg font-semibold text-fg lg:text-xl">{children}</h2>;
}

/** Active notices: the most prominent block, in the calm info tone. */
function Announcements({ page }: { page: CenterPageData }) {
  const { t } = useTranslation("portal");
  const pick = usePick();
  return (
    <section
      className="flex flex-col gap-3 rounded-card border border-info-border bg-info-bg p-4 text-info-fg lg:p-5"
      data-testid="center-announcements"
      aria-labelledby="center-announcements-title"
    >
      <h2 id="center-announcements-title" className="text-base font-semibold lg:text-lg">
        {t("center.announcements")}
      </h2>
      <ul className="flex flex-col divide-y divide-info-border">
        {page.announcements.map((a) => {
          const body = pick(a.body_ar, a.body_en);
          return (
            <li key={a.id} className="flex flex-col gap-1 py-3 first:pt-0 last:pb-0" data-testid="center-announcement">
              <p className="text-sm font-semibold lg:text-base">{pick(a.title_ar, a.title_en)}</p>
              {body ? <p className="text-sm text-pretty whitespace-pre-line lg:text-base">{body}</p> : null}
              {a.ends_on ? (
                <p className="text-xs">
                  {t("center.until")} <DateText value={a.ends_on} />
                </p>
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function DayPill({ label, today }: { label: string; today: boolean }) {
  const { t } = useTranslation("portal");
  return (
    <span
      className={cn(
        "inline-flex min-h-7 items-center rounded-full border px-2.5 text-xs font-medium",
        today ? "border-transparent bg-primary-soft text-primary-strong" : "border-border bg-surface text-fg",
      )}
      data-today={today ? "true" : undefined}
    >
      {label}
      {today ? <span className="sr-only"> ({t("center.todayLabel")})</span> : null}
    </span>
  );
}

function DoctorCard({ doctor, todayWeekday }: { doctor: CenterDoctor; todayWeekday: number | undefined }) {
  const { t } = useTranslation("portal");
  const language = useLanguage();
  const pick = usePick();
  const name = pick(doctor.name_ar, doctor.name_en);
  const qualifications = pick(doctor.qualifications_ar, doctor.qualifications_en);
  const bio = pick(doctor.bio_ar, doctor.bio_en);
  const subtitle = [
    ...new Set(
      [pick(doctor.specialty_ar, doctor.specialty_en), pick(doctor.department_ar, doctor.department_en)].filter(
        Boolean,
      ),
    ),
  ].join(" · ");
  return (
    <li className="card-surface flex min-w-0 flex-col gap-4 p-4 lg:p-5" data-testid="center-doctor">
      <div className="flex items-center gap-3">
        {doctor.photo ? (
          <SiteImage
            image={doctor.photo}
            alt={t("center.photoOf", { name })}
            className="size-14 shrink-0 rounded-full"
          />
        ) : (
          <span
            aria-hidden="true"
            // ui-allow: the circle holds the doctor's initials (text that identifies a person), not an icon
            className="inline-flex size-12 shrink-0 items-center justify-center rounded-full bg-primary-soft text-base font-semibold text-primary-strong"
          >
            {initialsOf(name) || "·"}
          </span>
        )}
        <div className="min-w-0">
          <p className="text-base font-semibold text-balance break-words text-fg">{name}</p>
          {subtitle ? <p className="text-sm text-muted">{subtitle}</p> : null}
        </div>
      </div>
      {qualifications ? (
        <p className="text-sm text-fg" data-testid="center-doctor-qualifications">
          <span className="sr-only">{t("center.qualifications")}: </span>
          {qualifications}
        </p>
      ) : null}
      {bio ? <p className="text-sm text-pretty text-muted">{bio}</p> : null}
      <ul className="flex flex-col gap-2.5">
        {groupClinicDays(doctor.clinic_days).map((group) => (
          <li key={group.weekdays.join("-")} className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <span className="flex flex-wrap gap-1">
              {group.weekdays.map((d) => (
                <DayPill key={d} label={weekdayName(d, language, "short")} today={d === todayWeekday} />
              ))}
            </span>
            <span className="tabular text-sm text-muted">
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
  );
}

function Doctors({ page }: { page: CenterPageData }) {
  const { t } = useTranslation("portal");
  return (
    <section className="flex flex-col gap-3" data-testid="center-doctors" aria-labelledby="center-doctors-title">
      <h2 id="center-doctors-title" className="text-lg font-semibold text-fg lg:text-xl">
        {t("center.doctors")}
      </h2>
      <ul className="grid gap-3 sm:grid-cols-2">
        {page.doctors.map((doctor) => (
          <DoctorCard key={doctor.id} doctor={doctor} todayWeekday={page.today?.weekday} />
        ))}
      </ul>
    </section>
  );
}

function Departments({ page }: { page: CenterPageData }) {
  const { t } = useTranslation("portal");
  const pick = usePick();
  const withServices = page.departments.some((d) => d.services.length > 0);
  return (
    <section className="flex flex-col gap-3" data-testid="center-departments">
      <SectionTitle>{withServices ? t("center.services") : t("center.departments")}</SectionTitle>
      {withServices ? (
        <ul className="grid gap-3 sm:grid-cols-2">
          {page.departments.map((d) => (
            <li key={d.id} className="card-surface flex min-w-0 flex-col gap-2 p-4" data-testid="center-department">
              <p className="text-base font-semibold break-words text-fg">{pick(d.name_ar, d.name_en)}</p>
              {d.services.length > 0 ? (
                <ul className="flex flex-col gap-1" data-testid="center-services">
                  {d.services.map((service) => (
                    <li key={service.id} className="flex items-start gap-2 text-sm text-fg">
                      <Check className="mt-0.5 size-4 shrink-0 text-primary-strong" aria-hidden="true" />
                      <span className="min-w-0 break-words">{pick(service.name_ar, service.name_en)}</span>
                    </li>
                  ))}
                </ul>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <ul className="flex flex-wrap gap-2">
          {page.departments.map((d) => (
            <li
              key={d.id}
              className="inline-flex min-h-9 items-center rounded-full border border-border bg-surface px-4 text-sm font-medium text-fg"
            >
              {pick(d.name_ar, d.name_en)}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function About({ page }: { page: CenterPageData }) {
  const { t } = useTranslation("portal");
  const pick = usePick();
  const about = pick(page.about_ar, page.about_en);
  return (
    <section className="flex flex-col gap-3" data-testid="center-about" aria-labelledby="center-about-title">
      <h2 id="center-about-title" className="text-lg font-semibold text-fg lg:text-xl">
        {t("center.about")}
      </h2>
      {about ? <p className="text-base text-pretty whitespace-pre-line text-fg">{about}</p> : null}
      {page.gallery.length > 0 ? (
        <ul
          className="grid grid-cols-2 gap-2 sm:grid-cols-3"
          aria-label={t("center.gallery")}
          data-testid="center-gallery"
        >
          {page.gallery.map((image) => (
            <li key={image.id} className="min-w-0">
              <SiteImage image={image} className="aspect-[4/3] w-full rounded-control" />
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function Facilities({ page }: { page: CenterPageData }) {
  const { t } = useTranslation("portal");
  const pick = usePick();
  return (
    <section className="flex flex-col gap-3" data-testid="center-facilities">
      <SectionTitle>{t("center.facilities")}</SectionTitle>
      <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {page.facilities.map((f, index) => (
          <li
            key={index}
            className="flex min-h-11 items-center gap-2 rounded-control border border-border bg-surface px-3 py-2 text-sm font-medium text-fg"
          >
            <Check className="size-4 shrink-0 text-primary-strong" aria-hidden="true" />
            <span className="min-w-0 break-words">{pick(f.name_ar, f.name_en)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Reasons({ page }: { page: CenterPageData }) {
  const { t } = useTranslation("portal");
  const pick = usePick();
  return (
    <section className="flex flex-col gap-3" data-testid="center-reasons">
      <SectionTitle>{t("center.reasons")}</SectionTitle>
      <ul className="grid gap-3 sm:grid-cols-2">
        {page.reasons.map((r, index) => {
          const text = pick(r.text_ar, r.text_en);
          return (
            <li key={index} className="card-surface flex min-w-0 flex-col gap-1 p-4">
              <p className="text-base font-semibold break-words text-fg">{pick(r.title_ar, r.title_en)}</p>
              {text ? <p className="text-sm text-pretty text-muted">{text}</p> : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** "Fees are paid at reception" and the cancellation policy (ADR 0029 A5: no fees online). */
function FeesNote({ page }: { page: CenterPageData }) {
  const { t } = useTranslation("portal");
  const pick = usePick();
  const policy = pick(page.cancellation_policy_ar, page.cancellation_policy_en);
  return (
    <section className="card-surface flex min-w-0 flex-col gap-2 p-4 lg:p-5" data-testid="center-fees">
      <SectionTitle>{t("center.fees.title")}</SectionTitle>
      <p className="text-sm text-pretty text-fg">{t("center.fees.text")}</p>
      {policy ? (
        <div className="flex flex-col gap-1 border-t border-border pt-2">
          <p className="text-sm font-semibold text-fg">{t("center.fees.cancellation")}</p>
          <p className="text-sm text-pretty whitespace-pre-line text-muted">{policy}</p>
        </div>
      ) : null}
    </section>
  );
}

function Insurance({ page }: { page: CenterPageData }) {
  const { t } = useTranslation("portal");
  const pick = usePick();
  return (
    <section className="card-surface flex min-w-0 flex-col gap-3 p-4 lg:p-5" data-testid="center-insurance">
      <SectionTitle>{t("center.insurance")}</SectionTitle>
      <ul className="flex flex-wrap gap-2">
        {page.insurance.map((p) => (
          <li
            key={p.id}
            className="inline-flex min-h-9 items-center rounded-full border border-border bg-surface px-4 text-sm font-medium text-fg"
          >
            {pick(p.name_ar, p.name_en)}
          </li>
        ))}
      </ul>
      <p className="text-sm text-pretty text-muted">{t("center.insuranceHint")}</p>
    </section>
  );
}

function Faq({ page }: { page: CenterPageData }) {
  const { t } = useTranslation("portal");
  const pick = usePick();
  return (
    <section className="flex flex-col gap-3" data-testid="center-faq" aria-labelledby="center-faq-title">
      <h2 id="center-faq-title" className="text-lg font-semibold text-fg lg:text-xl">
        {t("center.faq")}
      </h2>
      <div className="card-surface flex flex-col divide-y divide-border">
        {page.faq.map((q) => (
          <details key={q.id} className="group min-w-0 px-4 lg:px-5" data-testid="center-faq-item">
            <summary className="flex min-h-12 cursor-pointer list-none items-center justify-between gap-3 py-3 text-sm font-semibold text-fg focus-ring lg:text-base">
              <span className="min-w-0 break-words">{pick(q.question_ar, q.question_en)}</span>
              <span aria-hidden="true" className="shrink-0 text-muted transition-transform group-open:rotate-45">
                +
              </span>
            </summary>
            <p className="pb-4 text-sm text-pretty whitespace-pre-line text-muted lg:text-base">
              {pick(q.answer_ar, q.answer_en)}
            </p>
          </details>
        ))}
      </div>
    </section>
  );
}

function Testimonials({ page }: { page: CenterPageData }) {
  const { t } = useTranslation("portal");
  const pick = usePick();
  return (
    <section className="flex flex-col gap-3" data-testid="center-testimonials">
      <SectionTitle>{t("center.testimonials")}</SectionTitle>
      <ul className="grid gap-3 sm:grid-cols-2">
        {page.testimonials.map((item) => {
          const author = pick(item.author_ar, item.author_en);
          return (
            <li key={item.id} className="min-w-0">
              <figure className="card-surface flex h-full flex-col gap-3 p-4 lg:p-5">
                <blockquote className="text-base text-pretty text-fg">{pick(item.text_ar, item.text_en)}</blockquote>
                {author ? <figcaption className="text-sm text-muted">{author}</figcaption> : null}
              </figure>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function Accessibility({ text }: { text: string }) {
  const { t } = useTranslation("portal");
  return (
    <section className="card-surface flex min-w-0 flex-col gap-2 p-4 lg:p-5" data-testid="center-accessibility">
      <SectionTitle>{t("center.accessibility")}</SectionTitle>
      <p className="text-sm text-pretty whitespace-pre-line text-fg lg:text-base">{text}</p>
    </section>
  );
}

/** The page's own footer: privacy and cancellation policies, opened on demand. */
function Policies({ page }: { page: CenterPageData }) {
  const { t } = useTranslation("portal");
  const pick = usePick();
  const items = [
    { key: "privacy", text: pick(page.privacy_ar, page.privacy_en) },
    { key: "cancellation", text: pick(page.cancellation_policy_ar, page.cancellation_policy_en) },
  ].filter((item) => item.text);
  if (items.length === 0) return null;
  return (
    <nav aria-label={t("center.policies.label")} className="flex flex-col gap-2" data-testid="center-policies">
      {items.map((item) => (
        <details key={item.key} className="group card-surface min-w-0 px-4">
          <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-3 py-2 text-sm font-medium text-fg focus-ring">
            {t(`center.policies.${item.key}`)}
            <span aria-hidden="true" className="text-muted transition-transform group-open:rotate-45">
              +
            </span>
          </summary>
          <p className="pb-3 text-sm text-pretty whitespace-pre-line text-muted">{item.text}</p>
        </details>
      ))}
    </nav>
  );
}

function Hours({ page }: { page: CenterPageData }) {
  const { t } = useTranslation("portal");
  const language = useLanguage();
  const byDay = new Map(page.hours.map((h) => [h.weekday, h]));
  return (
    <section className="card-surface flex min-w-0 flex-col gap-3 p-4 lg:p-5" data-testid="center-hours">
      <SectionTitle>{t("center.hours")}</SectionTitle>
      <dl className="flex flex-col gap-0.5">
        {WEEK_ORDER.map((weekday) => {
          const day = byDay.get(weekday);
          if (!day) return null;
          const isToday = page.today?.weekday === weekday;
          const off = day.closed || !day.opens || !day.closes;
          return (
            <div
              key={weekday}
              className={cn(
                "flex min-h-10 items-center justify-between gap-3 rounded-control px-3 py-1.5 text-sm",
                isToday && "bg-primary-soft font-semibold",
              )}
              aria-current={isToday ? "date" : undefined}
              data-testid={isToday ? "center-hours-today" : undefined}
            >
              <dt className={off && !isToday ? "text-muted" : "text-fg"}>
                {weekdayName(weekday, language)}
                {isToday ? (
                  <span className="ms-2 rounded-full bg-primary px-2 py-0.5 text-xs font-medium text-primary-fg">
                    {t("center.todayLabel")}
                  </span>
                ) : null}
              </dt>
              <dd className={cn("tabular", off ? "text-muted" : "text-fg")}>
                {off
                  ? t("center.closed")
                  : t("center.span", {
                      from: formatClock(day.opens ?? "", language),
                      to: formatClock(day.closes ?? "", language),
                    })}
              </dd>
            </div>
          );
        })}
      </dl>
    </section>
  );
}

const contactLink =
  "flex min-h-12 items-center gap-3 rounded-control border border-border bg-surface px-3 py-2 text-fg transition-colors hover:bg-accent focus-ring";

function ContactLine({ icon, label, children }: { icon: ReactNode; label: string; children: ReactNode }) {
  return (
    <>
      <span className="shrink-0 text-muted">{icon}</span>
      <span className="flex min-w-0 flex-col">
        <span className="text-xs text-muted">{label}</span>
        <span className="text-sm font-medium break-words">{children}</span>
      </span>
    </>
  );
}

function Contact({ page }: { page: CenterPageData }) {
  const { t } = useTranslation("portal");
  const pick = usePick();
  const directions = pick(page.directions_ar, page.directions_en);
  const hasContact = Boolean(page.phone_uri || page.whatsapp || page.email || page.maps_url);
  const hasAddress = Boolean(page.address || directions);
  if (!hasContact && !hasAddress) return null;
  return (
    <section className="card-surface flex min-w-0 flex-col gap-3 p-4 lg:p-5" data-testid="center-contact">
      <SectionTitle>{t("center.contact")}</SectionTitle>
      <ul className="grid gap-2 md:grid-cols-2">
        {page.phone_uri ? (
          <li>
            <a href={page.phone_uri} className={contactLink} data-testid="center-phone">
              <ContactLine icon={<Phone className="size-4" aria-hidden="true" />} label={t("center.call")}>
                <span className="num">{page.phone}</span>
              </ContactLine>
            </a>
          </li>
        ) : null}
        {page.whatsapp ? (
          <li>
            <a
              href={`https://wa.me/${page.whatsapp}`}
              rel="noopener noreferrer"
              className={contactLink}
              data-testid="center-whatsapp"
            >
              <ContactLine icon={<MessageCircle className="size-4" aria-hidden="true" />} label={t("center.whatsapp")}>
                <span className="num">+{page.whatsapp}</span>
              </ContactLine>
            </a>
          </li>
        ) : null}
        {page.email ? (
          <li>
            <a href={`mailto:${page.email}`} className={contactLink} data-testid="center-email">
              <ContactLine icon={<Mail className="size-4" aria-hidden="true" />} label={t("center.email")}>
                <span dir="ltr" className="break-all">
                  {page.email}
                </span>
              </ContactLine>
            </a>
          </li>
        ) : null}
        {hasAddress ? (
          <li
            id={ADDRESS_ID}
            className="flex scroll-mt-24 items-start gap-3 px-1 pt-1 md:col-span-2"
            data-testid="center-address"
          >
            <span className="mt-0.5 shrink-0 text-muted">
              <MapPin className="size-4" aria-hidden="true" />
            </span>
            <span className="flex min-w-0 flex-col gap-1">
              <span className="text-xs text-muted">{t("center.address")}</span>
              {page.address ? <span className="text-sm font-medium text-pretty text-fg">{page.address}</span> : null}
              {directions ? <span className="text-sm text-pretty text-muted">{directions}</span> : null}
            </span>
          </li>
        ) : null}
        {page.maps_url ? (
          <li>
            {/* A plain link the visitor's phone opens, like wa.me: nothing is embedded or fetched. */}
            <a
              href={page.maps_url}
              rel="noopener noreferrer"
              target="_blank"
              className={contactLink}
              data-testid="center-maps"
            >
              <ContactLine icon={<MapPin className="size-4" aria-hidden="true" />} label={t("center.address")}>
                <span className="flex items-center gap-1.5">
                  {t("center.maps")}
                  <ExternalLink className="size-3.5" aria-hidden="true" />
                </span>
              </ContactLine>
            </a>
          </li>
        ) : null}
      </ul>
    </section>
  );
}

/** How to sign in: what the visitor needs and where to find it (a guide, not a second action). */
function HowToSignIn({ wide }: { wide?: boolean }) {
  const { t } = useTranslation("portal");
  const steps = ["file", "phone", "code"] as const;
  return (
    <section
      className="card-surface flex min-w-0 flex-col gap-4 p-4 lg:p-5"
      data-testid="center-how"
      aria-labelledby="center-how-title"
    >
      <h2 id="center-how-title" className="text-lg font-semibold text-fg lg:text-xl">
        {t("center.how.title")}
      </h2>
      <ol className={cn("flex flex-col gap-4", wide && "lg:flex-row lg:gap-8")}>
        {steps.map((step, index) => (
          <li key={step} className="flex min-w-0 flex-1 items-start gap-3">
            <span
              aria-hidden="true"
              className="inline-flex size-7 shrink-0 items-center justify-center rounded-full bg-primary-soft num text-sm font-semibold text-primary-strong"
            >
              {index + 1}
            </span>
            <span className="flex min-w-0 flex-col gap-0.5">
              <span className="text-sm font-semibold text-fg">{t(`center.how.${step}.title`)}</span>
              <span className="text-sm text-pretty text-muted">{t(`center.how.${step}.text`)}</span>
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}

function EndBand() {
  const { t } = useTranslation("portal");
  return (
    <section className="card-surface flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between lg:p-8">
      <p className="text-base font-medium text-pretty text-fg lg:text-lg">{t("center.endPrompt")}</p>
      <SignInAction className="sm:shrink-0" />
    </section>
  );
}

/** Phones only: the action stays in reach; the layout footer reserves its height. */
function StickyBar() {
  return (
    <div
      className="fixed inset-x-0 bottom-0 z-20 border-t border-border bg-surface px-4 pt-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] md:hidden print:hidden"
      data-testid="center-sticky-bar"
    >
      <SignInAction testId="center-sticky-cta" />
    </div>
  );
}

function Loading() {
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem] lg:gap-8" aria-hidden="true">
      <div className="grid gap-4">
        <Skeleton className="h-28" />
        <Skeleton className="h-40" />
      </div>
      <Skeleton className="h-64" />
    </div>
  );
}

/**
 * The center website at the portal's door (before sign-in), ADR 0023, 0029 H, D-0017, D-0020,
 * D-0021. Sections in this order: hero, notices, about (with gallery), facilities, reasons,
 * departments with service names, doctors (qualifications, photo, clinic days), hours with
 * "fees are paid at reception" and the cancellation policy, insurers, FAQ, testimonials,
 * accessibility, contact with a plain maps link, and the policies footer. Phones read one column
 * in that order with quick actions and a sticky bottom bar; from lg the hours, fees and sign-in
 * guide sit in a side column beside the content. An empty or hidden section is left out, never
 * shown as a placeholder. No prices anywhere.
 */
export function CenterPage() {
  const { t } = useTranslation(["portal", "errors"]);
  const translateError = useTranslateError();
  const identityName = useCenterName();
  const center = useCenterPage();
  const pick = usePick();
  const page = center.data;
  // The page answer carries the center's name; the identity read is the fallback while it loads.
  const name = (page ? pick(page.name_ar, page.name_en) : "") || identityName;
  useDocumentTitle(name);

  const hasNotices = Boolean(page && page.announcements.length > 0);
  const hasAbout = Boolean(page && (pick(page.about_ar, page.about_en) || page.gallery.length > 0));
  const hasFacilities = Boolean(page && page.facilities.length > 0);
  const hasReasons = Boolean(page && page.reasons.length > 0);
  const hasDoctors = Boolean(page && page.doctors.length > 0);
  const hasDepartments = Boolean(page && page.departments.length > 0);
  const hasHours = Boolean(page && page.hours.length > 0);
  const hasInsurance = Boolean(page && page.insurance.length > 0);
  const hasFaq = Boolean(page && page.faq.length > 0);
  const hasTestimonials = Boolean(page && page.testimonials.length > 0);
  const accessibility = page ? pick(page.accessibility_ar, page.accessibility_en) : "";
  const hasContact = Boolean(
    page &&
    (page.phone_uri ||
      page.whatsapp ||
      page.email ||
      page.address ||
      page.maps_url ||
      pick(page.directions_ar, page.directions_en)),
  );
  // The fees line belongs with something to visit or book; a policy alone also brings it.
  const hasFees = Boolean(
    page && (hasDoctors || hasDepartments || pick(page.cancellation_policy_ar, page.cancellation_policy_en)),
  );
  const hasMain = hasAbout || hasFacilities || hasReasons || hasDoctors || hasDepartments;
  // Patient sign-in switched off (ADR 0029): the page keeps its facts and drops every sign-in call.
  const tracking = getSiteConfig().patientTracking;
  return (
    <div className="flex min-w-0 flex-col gap-5 lg:gap-8" data-testid="center-page">
      <Hero page={page} name={name} />

      {center.isPending ? (
        <Loading />
      ) : center.isError ? (
        <AlertCard variant="warning" title={t("center.unavailable")}>
          {translateError(center.error)}
        </AlertCard>
      ) : page ? (
        <>
          <QuickActions page={page} />
          {hasNotices ? <Announcements page={page} /> : null}
          {/* Phones read one column in the page's order: about, facilities, reasons, services,
              doctors, then hours, fees and the sign-in guide. From lg those three sit beside. */}
          {hasMain ? (
            <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_22rem] lg:items-start lg:gap-8 xl:grid-cols-[minmax(0,1fr)_24rem]">
              <div className="flex min-w-0 flex-col gap-5 lg:gap-8">
                {hasAbout ? <About page={page} /> : null}
                {hasFacilities ? <Facilities page={page} /> : null}
                {hasReasons ? <Reasons page={page} /> : null}
                {hasDepartments ? <Departments page={page} /> : null}
                {hasDoctors ? <Doctors page={page} /> : null}
              </div>
              {/* Sticky only when the column fits the screen's height; else it scrolls with the page. */}
              <div
                className="flex min-w-0 flex-col gap-5 lg:[@media(min-height:880px)]:sticky lg:[@media(min-height:880px)]:top-20"
                data-testid="center-side"
              >
                {hasHours ? <Hours page={page} /> : null}
                {hasFees ? <FeesNote page={page} /> : null}
                {tracking ? <HowToSignIn /> : null}
              </div>
            </div>
          ) : (
            <div className="flex flex-col gap-5 lg:gap-8" data-testid="center-side">
              {hasHours || hasFees ? (
                <div className="grid gap-5 md:grid-cols-2 md:items-start lg:gap-8">
                  {hasHours ? <Hours page={page} /> : null}
                  {hasFees ? <FeesNote page={page} /> : null}
                </div>
              ) : null}
              {tracking ? <HowToSignIn wide /> : null}
            </div>
          )}
          {hasInsurance ? <Insurance page={page} /> : null}
          {hasFaq ? <Faq page={page} /> : null}
          {hasTestimonials ? <Testimonials page={page} /> : null}
          {accessibility ? <Accessibility text={accessibility} /> : null}
          {hasContact ? <Contact page={page} /> : null}
          {tracking ? <EndBand /> : null}
          <Policies page={page} />
        </>
      ) : null}
      {tracking ? <StickyBar /> : null}
    </div>
  );
}
