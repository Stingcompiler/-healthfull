import { Link } from "@tanstack/react-router";
import {
  CalendarCheck,
  CalendarPlus,
  Check,
  ChevronDown,
  Clock,
  ExternalLink,
  FolderOpen,
  Mail,
  MapPin,
  MessageCircle,
  Phone,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { DateText } from "@/components/DateText";
import { ChevronNext } from "@/components/icons";
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
import { CenterMark } from "../components/CenterMark";
import { centerTasks, POLICIES_ID, stickyBar, type BookTarget } from "../lib/center-tasks";
import { usePick } from "../lib/ui";
import { useCenterTaskInput } from "../lib/use-center-tasks";

const ADDRESS_ID = "center-address";
const HOURS_ID = "center-hours";

/** The website's larger card radius (`.site-card`), for surfaces that are not a `.site-card`. */
const SITE_RADIUS = "rounded-[calc(var(--card-radius)+0.5rem)]";

/** Scrolls to a section of the page (the "directions" and "hours" tasks: nothing is fetched). */
function goTo(id: string) {
  const target = document.getElementById(id);
  if (!target) return;
  const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  target.scrollIntoView({ behavior: calm ? "auto" : "smooth", block: "start" });
}

/**
 * Sections marked `data-reveal` rise in once when they first scroll into view. A section already
 * on screen at load, or any section under reduced motion or without IntersectionObserver, simply
 * stays as it is (visible by default: nothing waits for script to appear).
 */
function useRevealOnScroll(ready: boolean) {
  useEffect(() => {
    if (!ready || typeof IntersectionObserver === "undefined") return;
    if (typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      return;
    }
    const seen = new WeakSet<Element>();
    const observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!seen.has(entry.target)) {
          // First report: the section's place at load. On screen already: leave it alone.
          seen.add(entry.target);
          if (entry.isIntersecting) observer.unobserve(entry.target);
        } else if (entry.isIntersecting) {
          entry.target.classList.add("site-reveal");
          observer.unobserve(entry.target);
        }
      }
    });
    document.querySelectorAll("[data-reveal]").forEach((node) => {
      observer.observe(node);
    });
    return () => {
      observer.disconnect();
    };
  }, [ready]);
}

/** Today's status as a chip: on the hero photo it is glass, elsewhere a quiet surface. */
function StatusChip({ page, glass = false }: { page: CenterPageData; glass?: boolean }) {
  const text = useOpenStatusText(page.today, page.hours);
  if (!page.today || !text) return null;
  const open = page.today.state === "open";
  return (
    <span
      className={cn(
        "inline-flex w-fit max-w-full items-center gap-2 rounded-full border border-border px-3 py-1.5 text-sm font-medium text-fg",
        glass ? "site-glass shadow-card" : "bg-surface",
      )}
      data-testid="center-today"
      data-open={open ? "true" : undefined}
    >
      <span aria-hidden="true" className={cn("size-2 shrink-0 rounded-full", open ? "bg-success" : "bg-fg-muted")} />
      <span className="min-w-0">{text}</span>
    </span>
  );
}

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
 * The identity: logo or monogram, name, today's status and the center's opening words. The photo
 * is a short banner on phones (it never fills the first screen) and an inset panel beside the
 * text from lg, with the status chip in glass over it.
 */
function Hero({ page, name }: { page: CenterPageData | undefined; name: string }) {
  const pick = usePick();
  const title = page ? pick(page.hero_title_ar, page.hero_title_en) : "";
  const text = page ? pick(page.hero_text_ar, page.hero_text_en) : "";
  const image = page?.hero_image ?? null;
  return (
    <section className="site-card site-reveal overflow-hidden" aria-labelledby="center-name" data-testid="center-hero">
      <div
        className={cn(
          "grid",
          image && "lg:grid-cols-[minmax(0,1fr)_minmax(0,24rem)] xl:grid-cols-[minmax(0,1fr)_28rem]",
        )}
      >
        <div className="flex min-w-0 flex-col gap-4 p-5 sm:p-7 lg:justify-center lg:p-10">
          <div className="flex items-center gap-4">
            <CenterMark
              logoUrl={page?.logo_url}
              name={name}
              className="size-14 text-xl sm:size-16 sm:text-2xl lg:size-20 lg:text-3xl"
            />
            <h1
              id="center-name"
              className="min-w-0 text-[1.75rem] leading-tight font-bold text-balance break-words text-fg sm:text-4xl lg:text-[2.5rem]"
            >
              {name}
            </h1>
          </div>
          {page && !image ? <StatusChip page={page} /> : null}
          {title ? (
            <p className="text-lg font-semibold text-balance text-fg lg:text-xl" data-testid="center-hero-title">
              {title}
            </p>
          ) : null}
          {text ? <p className="max-w-prose text-base text-pretty text-muted lg:text-lg">{text}</p> : null}
        </div>
        {image ? (
          <div className="relative p-2 max-lg:order-first sm:p-3">
            <SiteImage
              image={image}
              eager
              className={cn(SITE_RADIUS, "h-36 w-full sm:h-48 lg:h-full lg:max-h-[24rem] lg:min-h-72")}
            />
            {page ? (
              <div className="absolute start-5 bottom-5 max-w-[calc(100%-2.5rem)] sm:start-6 sm:bottom-6">
                <StatusChip page={page} glass />
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </section>
  );
}

const taskBase = cn(SITE_RADIUS, "site-lift flex min-w-0 items-center gap-4 p-4 text-start focus-ring sm:p-5");

/** One large task: the page's main ways in (book, open a booking, sign in). */
function TaskCard({
  to,
  icon,
  title,
  hint,
  primary = false,
  testId,
}: {
  to: BookTarget | "/portal/sign-in" | "/portal/home" | "/portal/booking";
  icon: ReactNode;
  title: string;
  hint: string;
  primary?: boolean;
  testId: string;
}) {
  return (
    <Link
      to={to}
      data-testid={testId}
      className={cn(
        taskBase,
        "min-h-24",
        primary ? "border border-transparent bg-primary text-primary-fg shadow-card" : "site-card text-fg",
      )}
    >
      <span className={cn("shrink-0 [&>svg]:size-7", primary ? "text-primary-fg" : "text-primary-strong")}>{icon}</span>
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="text-base font-semibold text-balance lg:text-lg">{title}</span>
        <span className={cn("text-sm text-pretty", primary ? "text-primary-fg" : "text-muted")}>{hint}</span>
      </span>
      <ChevronNext aria-hidden="true" className="size-5 shrink-0" />
    </Link>
  );
}

const tileClass = cn(taskBase, "site-card min-h-[5.5rem] flex-col items-start gap-1.5 text-fg");

/** A compact contact task (call, WhatsApp, directions, today's hours). */
function TileBody({ icon, title, detail }: { icon: ReactNode; title: string; detail?: ReactNode }) {
  return (
    <>
      <span className="text-primary-strong [&>svg]:size-5">{icon}</span>
      <span className="text-sm font-semibold">{title}</span>
      {detail ? <span className="max-w-full truncate text-xs text-muted">{detail}</span> : null}
    </>
  );
}

function todaysHours(page: CenterPageData, closed: string, span: (from: string, to: string) => string): string {
  const weekday = page.today?.weekday;
  if (weekday === undefined) return "";
  const day = page.hours.find((h) => h.weekday === weekday);
  if (!day) return "";
  if (day.closed || !day.opens || !day.closes) return closed;
  return span(day.opens, day.closes);
}

/**
 * The first screen's answer to "what can I do here": large cards for booking, an existing guest
 * booking and the patient file, then compact cards for calling, WhatsApp, directions and today's
 * hours. Each appears only when its switch is on or the page has its data.
 */
function Tasks({ page }: { page: CenterPageData }) {
  const { t } = useTranslation("portal");
  const language = useLanguage();
  const input = useCenterTaskInput(page);
  const tasks = centerTasks(input);
  const signedIn = input.signedIn;

  const main: ReactNode[] = [];
  if (tasks.book) {
    main.push(
      <TaskCard
        key="book"
        to={tasks.book}
        testId="center-book"
        primary
        icon={<CalendarPlus aria-hidden="true" />}
        title={t("center.bookOnline")}
        hint={t("center.tasks.bookHint")}
      />,
    );
  } else if (tasks.bookViaSignIn) {
    main.push(
      <TaskCard
        key="book"
        to="/portal/sign-in"
        testId="quick-book"
        icon={<CalendarPlus aria-hidden="true" />}
        title={t("center.quick.book")}
        hint={t("center.tasks.bookViaSignInHint")}
      />,
    );
  }
  if (tasks.myBooking) {
    main.push(
      <TaskCard
        key="my-booking"
        to="/portal/booking"
        testId="quick-my-booking"
        icon={<CalendarCheck aria-hidden="true" />}
        title={t("center.tasks.myBooking")}
        hint={t("center.tasks.myBookingHint")}
      />,
    );
  }
  if (tasks.signIn) {
    main.push(
      <TaskCard
        key="sign-in"
        to={signedIn ? "/portal/home" : "/portal/sign-in"}
        testId="center-sign-in"
        primary={main.length === 0}
        icon={<FolderOpen aria-hidden="true" />}
        title={signedIn ? t("center.openFile") : t("center.signIn")}
        hint={signedIn ? t("center.tasks.openFileHint") : t("center.tasks.signInHint")}
      />,
    );
  }

  const contact: ReactNode[] = [];
  if (tasks.call) {
    contact.push(
      <a key="call" href={page.phone_uri} className={tileClass} data-testid="quick-call">
        <TileBody
          icon={<Phone aria-hidden="true" />}
          title={t("center.call")}
          detail={<span className="num">{page.phone}</span>}
        />
      </a>,
    );
  }
  if (tasks.whatsapp) {
    contact.push(
      <a
        key="wa"
        href={`https://wa.me/${page.whatsapp}`}
        rel="noopener noreferrer"
        className={tileClass}
        data-testid="quick-whatsapp"
      >
        <TileBody
          icon={<MessageCircle aria-hidden="true" />}
          title={t("center.whatsapp")}
          detail={<span className="num">+{page.whatsapp}</span>}
        />
      </a>,
    );
  }
  if (tasks.directions) {
    contact.push(
      <button
        key="dir"
        type="button"
        className={tileClass}
        onClick={() => {
          goTo(ADDRESS_ID);
        }}
        data-testid="quick-directions"
      >
        <TileBody
          icon={<MapPin aria-hidden="true" />}
          title={t("center.quick.directions")}
          detail={t("center.tasks.directionsHint")}
        />
      </button>,
    );
  }
  if (tasks.hours) {
    const today = todaysHours(page, t("center.tasks.hoursClosed"), (from, to) =>
      t("center.span", { from: formatClock(from, language), to: formatClock(to, language) }),
    );
    contact.push(
      <button
        key="hours"
        type="button"
        className={tileClass}
        onClick={() => {
          goTo(HOURS_ID);
        }}
        data-testid="quick-hours"
      >
        <TileBody
          icon={<Clock aria-hidden="true" />}
          title={today ? t("center.tasks.hours") : t("center.hours")}
          detail={today ? <span className="tabular">{today}</span> : undefined}
        />
      </button>,
    );
  }

  if (main.length === 0 && contact.length === 0) return null;
  return (
    <nav
      aria-labelledby="center-tasks-title"
      className="site-reveal flex flex-col gap-3 [animation-delay:80ms]"
      data-testid="center-quick-actions"
    >
      <h2 id="center-tasks-title" className="text-base font-semibold text-fg lg:text-lg">
        {t("center.tasks.title")}
      </h2>
      {main.length > 0 ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[repeat(auto-fit,minmax(15rem,1fr))] sm:[&>*:last-child:nth-child(odd)]:col-span-2 lg:[&>*:last-child:nth-child(odd)]:col-span-1">
          {main}
        </div>
      ) : null}
      {contact.length > 0 ? (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-[repeat(auto-fit,minmax(10rem,1fr))] [&>*:last-child:nth-child(odd)]:col-span-2 md:[&>*:last-child:nth-child(odd)]:col-span-1">
          {contact}
        </div>
      ) : null}
    </nav>
  );
}

function SectionTitle({ id, children }: { id?: string; children: ReactNode }) {
  return (
    <h2 id={id} className="text-lg font-semibold text-fg lg:text-xl">
      {children}
    </h2>
  );
}

/** Active notices: the most prominent block, in the calm info tone. */
function Announcements({ page }: { page: CenterPageData }) {
  const { t } = useTranslation("portal");
  const pick = usePick();
  return (
    <section
      className={cn(SITE_RADIUS, "flex flex-col gap-3 border border-info-border bg-info-bg p-5 text-info-fg lg:p-6")}
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
    <li className="site-card flex min-w-0 flex-col gap-4 p-5" data-testid="center-doctor">
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
      <ul className="mt-auto flex flex-col gap-2.5 border-t border-border pt-3">
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
    <section
      className="flex flex-col gap-3"
      data-testid="center-doctors"
      aria-labelledby="center-doctors-title"
      data-reveal
    >
      <SectionTitle id="center-doctors-title">{t("center.doctors")}</SectionTitle>
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
    <section
      className="flex flex-col gap-3"
      data-testid="center-departments"
      aria-labelledby="center-departments-title"
      data-reveal
    >
      <SectionTitle id="center-departments-title">
        {withServices ? t("center.services") : t("center.departments")}
      </SectionTitle>
      {withServices ? (
        <ul className="grid gap-3 sm:grid-cols-2">
          {page.departments.map((d) => (
            <li key={d.id} className="site-card flex min-w-0 flex-col gap-2 p-5" data-testid="center-department">
              <p className="text-base font-semibold break-words text-fg">{pick(d.name_ar, d.name_en)}</p>
              {d.services.length > 0 ? (
                <ul className="flex flex-col gap-1.5" data-testid="center-services">
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
              className="inline-flex min-h-10 items-center rounded-full border border-border bg-surface px-4 text-sm font-medium text-fg shadow-card"
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
    <section
      className="site-card flex flex-col gap-4 p-5 lg:p-7"
      data-testid="center-about"
      aria-labelledby="center-about-title"
      data-reveal
    >
      <SectionTitle id="center-about-title">{t("center.about")}</SectionTitle>
      {about ? <p className="max-w-prose text-base text-pretty whitespace-pre-line text-fg">{about}</p> : null}
      {page.gallery.length > 0 ? (
        <ul
          className="grid grid-cols-2 gap-2 sm:grid-cols-3"
          aria-label={t("center.gallery")}
          data-testid="center-gallery"
        >
          {page.gallery.map((image) => (
            <li key={image.id} className="min-w-0">
              <SiteImage image={image} className="aspect-[4/3] w-full rounded-card" />
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
    <section
      className="flex flex-col gap-3"
      data-testid="center-facilities"
      aria-labelledby="center-facilities-title"
      data-reveal
    >
      <SectionTitle id="center-facilities-title">{t("center.facilities")}</SectionTitle>
      <ul className="flex flex-wrap gap-2">
        {page.facilities.map((f, index) => (
          <li
            key={index}
            className="inline-flex min-h-10 max-w-full items-center gap-2 rounded-full border border-border bg-surface px-4 py-2 text-sm font-medium text-fg shadow-card"
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
    <section
      className="flex flex-col gap-3"
      data-testid="center-reasons"
      aria-labelledby="center-reasons-title"
      data-reveal
    >
      <SectionTitle id="center-reasons-title">{t("center.reasons")}</SectionTitle>
      <ul className="grid gap-3 sm:grid-cols-2">
        {page.reasons.map((r, index) => {
          const text = pick(r.text_ar, r.text_en);
          return (
            <li key={index} className="site-card flex min-w-0 flex-col gap-1.5 p-5">
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
    <section
      className="site-card flex min-w-0 flex-col gap-2 p-5"
      data-testid="center-fees"
      aria-labelledby="center-fees-title"
    >
      <SectionTitle id="center-fees-title">{t("center.fees.title")}</SectionTitle>
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
    <section
      className="site-card flex min-w-0 flex-col gap-3 p-5 lg:p-7"
      data-testid="center-insurance"
      aria-labelledby="center-insurance-title"
      data-reveal
    >
      <SectionTitle id="center-insurance-title">{t("center.insurance")}</SectionTitle>
      <ul className="flex flex-wrap gap-2">
        {page.insurance.map((p) => (
          <li
            key={p.id}
            className="inline-flex min-h-10 items-center rounded-full border border-border bg-subtle px-4 text-sm font-medium text-fg"
          >
            {pick(p.name_ar, p.name_en)}
          </li>
        ))}
      </ul>
      <p className="text-sm text-pretty text-muted">{t("center.insuranceHint")}</p>
    </section>
  );
}

/** An accordion row: a native <details> (keyboard and no-script friendly) that opens smoothly. */
function Disclosure({
  summary,
  children,
  testId,
  className,
}: {
  summary: ReactNode;
  children: ReactNode;
  testId?: string;
  className?: string;
}) {
  return (
    <details className={cn("site-accordion group min-w-0", className)} data-testid={testId}>
      <summary className="flex min-h-12 cursor-pointer list-none items-center justify-between gap-3 rounded-control py-3 text-sm font-semibold text-fg focus-ring lg:text-base [&::-webkit-details-marker]:hidden">
        <span className="min-w-0 break-words">{summary}</span>
        <ChevronDown
          aria-hidden="true"
          className="size-5 shrink-0 text-muted transition-transform duration-200 group-open:rotate-180"
        />
      </summary>
      <div className="pb-4 text-sm text-pretty whitespace-pre-line text-muted lg:text-base">{children}</div>
    </details>
  );
}

function Faq({ page }: { page: CenterPageData }) {
  const { t } = useTranslation("portal");
  const pick = usePick();
  return (
    <section className="flex flex-col gap-3" data-testid="center-faq" aria-labelledby="center-faq-title" data-reveal>
      <SectionTitle id="center-faq-title">{t("center.faq")}</SectionTitle>
      <div className="site-card flex flex-col divide-y divide-border px-5 lg:px-6">
        {page.faq.map((q) => (
          <Disclosure key={q.id} summary={pick(q.question_ar, q.question_en)} testId="center-faq-item">
            {pick(q.answer_ar, q.answer_en)}
          </Disclosure>
        ))}
      </div>
    </section>
  );
}

function Testimonials({ page }: { page: CenterPageData }) {
  const { t } = useTranslation("portal");
  const pick = usePick();
  return (
    <section
      className="flex flex-col gap-3"
      data-testid="center-testimonials"
      aria-labelledby="center-testimonials-title"
      data-reveal
    >
      <SectionTitle id="center-testimonials-title">{t("center.testimonials")}</SectionTitle>
      <ul className="grid gap-3 sm:grid-cols-2">
        {page.testimonials.map((item) => {
          const author = pick(item.author_ar, item.author_en);
          return (
            <li key={item.id} className="min-w-0">
              <figure className="site-card flex h-full flex-col gap-3 p-5 lg:p-6">
                <blockquote className="text-base text-pretty text-fg">{pick(item.text_ar, item.text_en)}</blockquote>
                {author ? <figcaption className="mt-auto text-sm text-muted">{author}</figcaption> : null}
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
    <section
      className="site-card flex min-w-0 flex-col gap-2 p-5 lg:p-7"
      data-testid="center-accessibility"
      aria-labelledby="center-accessibility-title"
      data-reveal
    >
      <SectionTitle id="center-accessibility-title">{t("center.accessibility")}</SectionTitle>
      <p className="text-sm text-pretty whitespace-pre-line text-fg lg:text-base">{text}</p>
    </section>
  );
}

/** The privacy and cancellation policies, opened on demand (the footer links here). */
function Policies({ page }: { page: CenterPageData }) {
  const { t } = useTranslation("portal");
  const pick = usePick();
  const items = [
    { key: "privacy" as const, text: pick(page.privacy_ar, page.privacy_en) },
    { key: "cancellation" as const, text: pick(page.cancellation_policy_ar, page.cancellation_policy_en) },
  ].filter((item) => item.text);
  if (items.length === 0) return null;
  return (
    <nav
      id={POLICIES_ID}
      aria-label={t("center.policies.label")}
      className="site-card flex scroll-mt-24 flex-col divide-y divide-border px-5"
      data-testid="center-policies"
    >
      {items.map((item) => (
        <Disclosure key={item.key} summary={t(`center.policies.${item.key}`)}>
          {item.text}
        </Disclosure>
      ))}
    </nav>
  );
}

function Hours({ page }: { page: CenterPageData }) {
  const { t } = useTranslation("portal");
  const language = useLanguage();
  const byDay = new Map(page.hours.map((h) => [h.weekday, h]));
  return (
    <section
      id={HOURS_ID}
      className="site-card flex min-w-0 scroll-mt-24 flex-col gap-3 p-5"
      data-testid="center-hours"
      aria-labelledby="center-hours-title"
    >
      <SectionTitle id="center-hours-title">{t("center.hours")}</SectionTitle>
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

const contactLink = cn(
  "flex min-h-12 items-center gap-3 rounded-card border border-border bg-surface px-3 py-2 text-fg focus-ring transition-colors hover:border-border-strong hover:bg-accent",
);

function ContactLine({ icon, label, children }: { icon: ReactNode; label: string; children: ReactNode }) {
  return (
    <>
      <span className="shrink-0 text-primary-strong">{icon}</span>
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
    <section
      className="site-card flex min-w-0 flex-col gap-4 p-5 lg:p-7"
      data-testid="center-contact"
      aria-labelledby="center-contact-title"
      data-reveal
    >
      <SectionTitle id="center-contact-title">{t("center.contact")}</SectionTitle>
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
        {hasAddress ? (
          <li
            id={ADDRESS_ID}
            className="flex scroll-mt-24 items-start gap-3 px-1 pt-1 md:col-span-2"
            data-testid="center-address"
          >
            <span className="mt-0.5 shrink-0 text-primary-strong">
              <MapPin className="size-4" aria-hidden="true" />
            </span>
            <span className="flex min-w-0 flex-col gap-1">
              <span className="text-xs text-muted">{t("center.address")}</span>
              {page.address ? <span className="text-sm font-medium text-pretty text-fg">{page.address}</span> : null}
              {directions ? <span className="text-sm text-pretty text-muted">{directions}</span> : null}
            </span>
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
      className="site-card flex min-w-0 flex-col gap-4 p-5"
      data-testid="center-how"
      aria-labelledby="center-how-title"
    >
      <SectionTitle id="center-how-title">{t("center.how.title")}</SectionTitle>
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

/** The closing call: the one way into the file, on the brand's soft surface. */
function EndBand() {
  const { t } = useTranslation("portal");
  const me = usePortalMe();
  const signedIn = Boolean(me.data);
  return (
    <section
      className={cn(
        SITE_RADIUS,
        "flex flex-col gap-4 border border-border bg-primary-soft p-5 sm:flex-row sm:items-center sm:justify-between lg:p-8",
      )}
      data-reveal
    >
      <p className="text-base font-medium text-pretty text-fg lg:text-lg">{t("center.endPrompt")}</p>
      <Link
        to={signedIn ? "/portal/home" : "/portal/sign-in"}
        data-testid="center-sign-in"
        className="site-lift inline-flex min-h-11 items-center justify-center gap-2 rounded-control bg-primary px-6 text-base font-medium text-primary-fg shadow-card focus-ring sm:shrink-0"
      >
        {signedIn ? t("center.openFile") : t("center.signIn")}
        <ChevronNext className="size-4" aria-hidden="true" />
      </Link>
    </section>
  );
}

/**
 * Phones only: booking, sign-in and a call button stay in reach on a floating glass bar. The
 * footer reserves its height (`stickyBar` decides both).
 */
function StickyBar({ page }: { page: CenterPageData | undefined }) {
  const { t } = useTranslation("portal");
  const input = useCenterTaskInput(page);
  const bar = stickyBar(input);
  if (!bar) return null;
  const signedIn = input.signedIn;
  const button =
    "site-lift inline-flex min-h-11 min-w-0 flex-1 items-center justify-center gap-2 rounded-control px-3 py-2 text-center text-sm font-medium focus-ring";
  // The first action is filled; a second one (sign-in beside booking) is outlined.
  return (
    <div
      className={cn(
        SITE_RADIUS,
        "site-glass fixed inset-x-3 bottom-[calc(0.75rem+env(safe-area-inset-bottom))] z-20 border border-border p-2 shadow-raised md:hidden print:hidden",
      )}
      data-testid="center-sticky-bar"
    >
      <div className="flex items-stretch gap-2">
        {bar.book ? (
          <Link to={bar.book} data-testid="center-sticky-book" className={cn(button, "bg-primary text-primary-fg")}>
            <CalendarPlus className="size-4 shrink-0" aria-hidden="true" />
            {t("center.bookOnline")}
          </Link>
        ) : null}
        {bar.signIn ? (
          <Link
            to={signedIn ? "/portal/home" : "/portal/sign-in"}
            data-testid="center-sticky-cta"
            className={cn(
              button,
              bar.book ? "border border-border-strong bg-surface text-fg" : "bg-primary text-primary-fg",
            )}
          >
            {signedIn ? t("center.openFile") : t("center.signIn")}
          </Link>
        ) : null}
        {bar.call && page ? (
          <a
            href={page.phone_uri}
            aria-label={t("center.sticky.call")}
            title={t("center.sticky.call")}
            data-testid="center-sticky-call"
            className={cn(
              button,
              bar.book || bar.signIn
                ? "w-11 flex-none border border-border-strong bg-surface px-0 text-fg"
                : "bg-primary text-primary-fg",
            )}
          >
            <Phone className="size-4 shrink-0" aria-hidden="true" />
            {bar.book || bar.signIn ? null : <span>{t("center.call")}</span>}
          </a>
        ) : null}
      </div>
    </div>
  );
}

function Loading() {
  return (
    <div className="grid gap-4" aria-hidden="true">
      <div className="grid gap-3 sm:grid-cols-2">
        <Skeleton className="h-24 rounded-card" />
        <Skeleton className="h-24 rounded-card" />
      </div>
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem] lg:gap-8">
        <Skeleton className="h-40 rounded-card" />
        <Skeleton className="h-64 rounded-card" />
      </div>
    </div>
  );
}

/**
 * The center website at the portal's door (before sign-in), ADR 0023, 0029 H, D-0017, D-0020,
 * D-0021, D-0022. The first screen answers "what can I do here": the identity, then task cards
 * (book online, open my booking, sign in, call, WhatsApp, directions, today's hours), each shown
 * only when its switch is on or the page has its data. Then the content in its fixed order:
 * notices, about (with gallery), facilities, reasons, departments with service names, doctors,
 * hours with "fees are paid at reception" and the cancellation policy, insurers, FAQ,
 * testimonials, accessibility, contact with a plain maps link, and the policies. From lg the
 * hours, fees and sign-in guide sit in a side column. An empty or hidden section is left out,
 * never shown as a placeholder. No prices anywhere. The footer is `CenterFooter` (PortalLayout).
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
  useRevealOnScroll(Boolean(page));

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
  // The fees line belongs with something to visit or book; a policy alone also brings it.
  const hasFees = Boolean(
    page && (hasDoctors || hasDepartments || pick(page.cancellation_policy_ar, page.cancellation_policy_en)),
  );
  const hasMain = hasAbout || hasFacilities || hasReasons || hasDoctors || hasDepartments;
  // Patient sign-in switched off (ADR 0029): the page keeps its facts and drops every sign-in call.
  const tracking = getSiteConfig().patientTracking;
  return (
    <div className="flex min-w-0 flex-col gap-6 lg:gap-10" data-testid="center-page">
      <div className="flex min-w-0 flex-col gap-5 lg:gap-6">
        <Hero page={page} name={name} />
        {page ? <Tasks page={page} /> : null}
      </div>

      {center.isPending ? (
        <Loading />
      ) : center.isError ? (
        <AlertCard variant="warning" title={t("center.unavailable")}>
          {translateError(center.error)}
        </AlertCard>
      ) : page ? (
        <>
          {hasNotices ? <Announcements page={page} /> : null}
          {/* Phones read one column in the page's order: about, facilities, reasons, services,
              doctors, then hours, fees and the sign-in guide. From lg those three sit beside. */}
          {hasMain ? (
            <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem] lg:items-start lg:gap-8 xl:grid-cols-[minmax(0,1fr)_24rem]">
              <div className="flex min-w-0 flex-col gap-6 lg:gap-10">
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
          <Contact page={page} />
          {tracking ? <EndBand /> : null}
          <Policies page={page} />
        </>
      ) : null}
      <StickyBar page={page} />
    </div>
  );
}
