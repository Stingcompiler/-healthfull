import { Link } from "@tanstack/react-router";
import {
  Ban,
  BellRing,
  Check,
  ChevronDown,
  FileX2,
  HardDrive,
  HeartPulse,
  History,
  Mail,
  PackageX,
  ShieldCheck,
  WifiOff,
  Zap,
} from "lucide-react";
import { useEffect, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { BrandMark } from "@/components/BrandMark";
import { ArrowNext } from "@/components/icons";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { ThemeSwitcher } from "@/components/ThemeSwitcher";
import { Button } from "@/components/ui/button";
import { useLanguage } from "@/lib/i18n-hooks";
import { getSiteConfig } from "@/lib/site";
import { cn } from "@/lib/utils";

import { HERO_WIDTHS, PHONE_WIDTHS, SCREEN_WIDTHS, shot, type Shot } from "./images";
import "./marketing.css";

/** The one call to action. Every copy leads to the staff sign-in (ADR 0027). */
function Cta({ place, className }: { place: string; className?: string }) {
  const { t } = useTranslation("marketing");
  return (
    <Button asChild size="lg" className={cn("mk-cta", className)}>
      <Link to="/sign-in" data-testid="mk-cta" data-cta={place}>
        {t("cta")}
        <ArrowNext aria-hidden="true" />
      </Link>
    </Button>
  );
}

function CtaBand({ place }: { place: string }) {
  return (
    <div className="mt-10 flex justify-center md:mt-12">
      <Cta place={place} />
    </div>
  );
}

function SectionHead({ id, title, lead }: { id: string; title: string; lead?: string }) {
  return (
    <div className="max-w-2xl">
      <h2 id={id} className="mk-section-title text-fg">
        {title}
      </h2>
      {lead ? <p className="mk-section-lead mt-3 text-muted">{lead}</p> : null}
    </div>
  );
}

function Picture({
  image,
  alt,
  sizes,
  eager = false,
  className,
}: {
  image: Shot;
  alt: string;
  sizes: string;
  eager?: boolean;
  className?: string;
}) {
  return (
    <img
      src={image.src}
      srcSet={image.srcSet}
      sizes={sizes}
      width={image.width}
      height={image.height}
      alt={alt}
      loading={eager ? "eager" : "lazy"}
      decoding={eager ? "sync" : "async"}
      {...(eager ? { fetchPriority: "high" as const } : {})}
      className={cn("block h-auto w-full", className)}
    />
  );
}

function setMeta(name: string, content: string): void {
  let tag = document.head.querySelector<HTMLMetaElement>(`meta[name="${name}"]`);
  if (!tag) {
    tag = document.createElement("meta");
    tag.name = name;
    document.head.append(tag);
  }
  tag.content = content;
}

/** Tab title and description follow the language; the Open Graph tags are static in index.html. */
function useMarketingHead(): void {
  const { t } = useTranslation("marketing");
  const title = t("meta.title");
  const description = t("meta.description");
  useEffect(() => {
    document.title = title;
    setMeta("description", description);
  }, [title, description]);
}

function Header() {
  const { t } = useTranslation("marketing");
  return (
    <header className="sticky top-0 z-30 border-b border-border bg-bg/95 backdrop-blur-sm">
      <div className="mk-wrap flex items-center justify-between gap-3 py-2">
        <span className="flex min-w-0 items-center gap-2.5" data-testid="mk-brand">
          <BrandMark />
          <span className="truncate text-base font-bold text-fg">{t("brand")}</span>
        </span>
        <div className="flex items-center gap-1 md:gap-3">
          <div role="group" aria-label={t("preferences")} className="flex items-center gap-1">
            <LanguageSwitcher />
            <ThemeSwitcher />
          </div>
          <Button asChild className="hidden font-semibold sm:inline-flex">
            <Link to="/sign-in" data-testid="mk-cta" data-cta="header">
              {t("cta")}
            </Link>
          </Button>
        </div>
      </div>
    </header>
  );
}

function Hero({ image }: { image: Shot }) {
  const { t } = useTranslation("marketing");
  return (
    <section aria-labelledby="mk-hero" className="mk-section pb-0 md:pb-0">
      <div className="mk-wrap">
        <div className="max-w-3xl">
          <h1 id="mk-hero" className="mk-hero-title text-fg">
            {t("hero.title")}
          </h1>
          <p className="mk-hero-lead mt-4 text-muted md:mt-5">{t("hero.lead")}</p>
          <div className="mt-6 flex flex-col items-start gap-3 sm:flex-row sm:items-center sm:gap-6 md:mt-8">
            <Cta place="hero" />
            <a
              href="#cycle"
              className="inline-flex min-h-11 items-center text-sm font-medium text-primary-strong underline-offset-4 hover:underline"
            >
              {t("hero.see")}
            </a>
          </div>
        </div>
        <div className="card-surface mt-8 overflow-hidden shadow-raised md:mt-12" data-testid="mk-hero-image">
          <Picture image={image} alt={t("hero.imageAlt")} sizes="(min-width: 1152px) 1072px, 100vw" eager />
        </div>
      </div>
    </section>
  );
}

const PROBLEMS = [
  { key: "p1", Icon: PackageX },
  { key: "p2", Icon: FileX2 },
  { key: "p3", Icon: History },
  { key: "p4", Icon: Ban },
] as const;

function Problem() {
  const { t } = useTranslation("marketing");
  return (
    <section aria-labelledby="mk-problem" className="mk-section">
      <div className="mk-wrap">
        <SectionHead id="mk-problem" title={t("problem.title")} lead={t("problem.lead")} />
        <ul className="card-surface mt-8 grid divide-y divide-border md:grid-cols-2 md:divide-y-0">
          {PROBLEMS.map(({ key, Icon }) => (
            <li key={key} className="mk-body flex items-start gap-3 p-5 md:border-b md:border-border">
              <Icon className="mt-1 size-5 shrink-0 text-danger-fg" aria-hidden="true" />
              <span className="text-fg">{t(`problem.${key}`)}</span>
            </li>
          ))}
        </ul>
        <p className="mk-body mt-6 max-w-2xl font-semibold text-fg">{t("problem.close")}</p>
      </div>
    </section>
  );
}

const STAGES = [
  { key: "before", items: ["reception", "doctor", "cashier"] },
  { key: "perform", items: ["lab", "pharmacy", "nursing"] },
  { key: "after", items: ["claims", "reports", "portal"] },
] as const;

function Cycle() {
  const { t } = useTranslation("marketing");
  return (
    <section id="cycle" aria-labelledby="mk-cycle" className="mk-section bg-subtle">
      <div className="mk-wrap">
        <SectionHead id="mk-cycle" title={t("cycle.title")} lead={t("cycle.lead")} />
        <ol className="card-surface mt-8 grid divide-y divide-border lg:grid-cols-3 lg:divide-x lg:divide-y-0">
          {STAGES.map((stage, index) => (
            <li key={stage.key} className="p-5 md:p-6">
              <p className="flex items-center gap-3">
                <span
                  className="inline-flex size-8 items-center justify-center rounded-full bg-primary num text-sm font-bold text-primary-fg"
                  aria-hidden="true"
                >
                  {index + 1}
                </span>
                <span className="mk-feature-title text-fg">{t(`cycle.${stage.key}`)}</span>
              </p>
              <ul className="mt-4 divide-y divide-border">
                {stage.items.map((item) => (
                  <li key={item} className="py-3 first:pt-0 last:pb-0">
                    <h3 className="text-base font-semibold text-fg">{t(`cycle.${item}.title`)}</h3>
                    <p className="mt-1 text-sm leading-relaxed text-muted">{t(`cycle.${item}.text`)}</p>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ol>
        <CtaBand place="cycle" />
      </div>
    </section>
  );
}

const RULES = ["r1", "r2", "r3", "r4", "r5", "r6", "r7"] as const;

function Safety() {
  const { t } = useTranslation("marketing");
  return (
    <section aria-labelledby="mk-safety" className="mk-section">
      <div className="mk-wrap">
        <SectionHead id="mk-safety" title={t("safety.title")} lead={t("safety.lead")} />
        <ul className="mt-8 grid gap-px overflow-hidden rounded-card border border-border bg-border lg:grid-cols-2">
          {RULES.map((rule) => (
            <li key={rule} className="flex items-start gap-4 bg-surface p-5 md:p-6 lg:last:col-span-2">
              <ShieldCheck className="mt-0.5 size-6 shrink-0 text-primary-strong" aria-hidden="true" />
              <div>
                <h3 className="text-base font-semibold text-fg">{t(`safety.${rule}.title`)}</h3>
                <p className="mt-1 text-sm leading-relaxed text-muted">{t(`safety.${rule}.text`)}</p>
              </div>
            </li>
          ))}
        </ul>
        <p className="mk-body mt-6 max-w-3xl text-muted">{t("safety.foot")}</p>
        <CtaBand place="safety" />
      </div>
    </section>
  );
}

const ROLE_KEYS = ["cashier", "doctor", "pharmacist", "lab", "manager", "accountant"] as const;

function Roles() {
  const { t } = useTranslation("marketing");
  const language = useLanguage();
  const images: Record<(typeof ROLE_KEYS)[number], Shot> = {
    cashier: shot(`cashier-${language}`, SCREEN_WIDTHS, 688),
    doctor: shot(`doctor-${language}`, SCREEN_WIDTHS, 688),
    pharmacist: shot(`pharmacy-${language}`, SCREEN_WIDTHS, 688),
    lab: shot(`lab-${language}`, SCREEN_WIDTHS, 688),
    manager: shot(`reports-${language}`, SCREEN_WIDTHS, 688),
    // Only the Arabic screen has demo data worth showing.
    accountant: shot("claims-ar", SCREEN_WIDTHS, 688),
  };
  return (
    <section aria-labelledby="mk-roles" className="mk-section bg-subtle">
      <div className="mk-wrap">
        <SectionHead id="mk-roles" title={t("roles.title")} lead={t("roles.lead")} />
        <ul className="mt-8 grid gap-4 md:grid-cols-2 md:gap-6">
          {ROLE_KEYS.map((role) => (
            <li key={role} className="card-surface flex flex-col overflow-hidden" data-testid={`mk-role-${role}`}>
              <Picture
                image={images[role]}
                alt={t(`roles.${role}.alt`)}
                sizes="(min-width: 1152px) 528px, (min-width: 768px) 45vw, 100vw"
                className="border-b border-border"
              />
              <div className="p-5">
                <h3 className="mk-feature-title text-fg">{t(`roles.${role}.title`)}</h3>
                <p className="mk-body mt-2 text-muted">{t(`roles.${role}.text`)}</p>
                {role === "accountant" && language === "en" ? (
                  <p className="mt-2 text-xs text-muted">{t("roles.accountant.note")}</p>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
        <CtaBand place="roles" />
      </div>
    </section>
  );
}

const NETWORK = [
  { key: "n1", Icon: WifiOff },
  { key: "n2", Icon: HardDrive },
  { key: "n3", Icon: HeartPulse },
  { key: "n4", Icon: Zap },
  { key: "n5", Icon: BellRing },
] as const;

function Network() {
  const { t } = useTranslation("marketing");
  return (
    <section aria-labelledby="mk-network" className="mk-section">
      <div className="mk-wrap">
        <SectionHead id="mk-network" title={t("network.title")} lead={t("network.lead")} />
        <ul className="mt-8 grid gap-8 md:grid-cols-2 lg:grid-cols-3">
          {NETWORK.map(({ key, Icon }) => (
            <li key={key} className="flex items-start gap-4">
              <Icon className="mt-0.5 size-6 shrink-0 text-primary-strong" aria-hidden="true" />
              <div>
                <h3 className="text-base font-semibold text-fg">{t(`network.${key}.title`)}</h3>
                <p className="mt-1 text-sm leading-relaxed text-muted">{t(`network.${key}.text`)}</p>
              </div>
            </li>
          ))}
        </ul>
        <CtaBand place="network" />
      </div>
    </section>
  );
}

const PORTAL_POINTS = ["p1", "p2", "p3"] as const;

function PortalSection() {
  const { t } = useTranslation("marketing");
  const language = useLanguage();
  const home = shot("portal-home", PHONE_WIDTHS, 1169);
  const results = shot("portal-results", PHONE_WIDTHS, 1169);
  return (
    <section aria-labelledby="mk-portal" className="mk-section bg-subtle">
      <div className="mk-wrap grid items-center gap-8 lg:grid-cols-2 lg:gap-12">
        <div>
          <SectionHead id="mk-portal" title={t("portal.title")} lead={t("portal.lead")} />
          <ul className="mk-body mt-6 flex flex-col gap-3 text-fg">
            {PORTAL_POINTS.map((key) => (
              <li key={key} className="flex items-start gap-3">
                <Check className="mt-1 size-5 shrink-0 text-primary-strong" aria-hidden="true" />
                <span>{t(`portal.${key}`)}</span>
              </li>
            ))}
          </ul>
          {language === "en" ? <p className="mt-4 text-xs text-muted">{t("portal.note")}</p> : null}
        </div>
        <div className="mx-auto grid w-full max-w-md grid-cols-2 gap-4">
          <div className="card-surface overflow-hidden">
            <Picture image={home} alt={t("portal.homeAlt")} sizes="(min-width: 448px) 212px, 45vw" />
          </div>
          <div className="card-surface overflow-hidden">
            <Picture image={results} alt={t("portal.resultsAlt")} sizes="(min-width: 448px) 212px, 45vw" />
          </div>
        </div>
      </div>
    </section>
  );
}

const QUESTIONS = ["1", "2", "3", "4", "5", "6"] as const;

function Faq() {
  const { t } = useTranslation("marketing");
  return (
    <section aria-labelledby="mk-faq" className="mk-section">
      <div className="mk-wrap">
        <SectionHead id="mk-faq" title={t("faq.title")} />
        <div className="mk-faq card-surface mt-8 max-w-3xl divide-y divide-border">
          {QUESTIONS.map((n) => (
            <details key={n} className="group">
              <summary className="flex min-h-14 cursor-pointer items-center justify-between gap-4 px-5 py-3 text-base font-semibold text-fg focus-ring-inset">
                <span>{t(`faq.q${n}`)}</span>
                <ChevronDown className="mk-faq-chevron size-5 shrink-0 text-muted" aria-hidden="true" />
              </summary>
              <p className="mk-body px-5 pb-4 text-muted">{t(`faq.a${n}`)}</p>
            </details>
          ))}
        </div>
      </div>
    </section>
  );
}

function Contact(): ReactNode {
  const { t } = useTranslation("marketing");
  const { contactEmail, contactWhatsapp } = getSiteConfig();
  if (!contactEmail && !contactWhatsapp) {
    return <p className="mk-body mt-6 text-muted">{t("final.demo")}</p>;
  }
  return (
    <div className="mt-6">
      <p className="mk-body text-muted">{t("final.demo")}</p>
      <p className="mt-3 text-sm font-semibold text-fg">{t("final.contact")}</p>
      <ul className="mt-1 flex flex-wrap gap-x-6">
        {contactEmail ? (
          <li>
            <a
              href={`mailto:${contactEmail}`}
              className="inline-flex min-h-11 items-center gap-2 text-sm font-medium text-primary-strong underline-offset-4 hover:underline"
            >
              <Mail className="size-4" aria-hidden="true" />
              <span>{t("final.email")}:</span>
              <span dir="ltr" className="num">
                {contactEmail}
              </span>
            </a>
          </li>
        ) : null}
        {contactWhatsapp ? (
          <li>
            <a
              href={`https://wa.me/${contactWhatsapp}`}
              rel="noopener noreferrer"
              className="inline-flex min-h-11 items-center gap-2 text-sm font-medium text-primary-strong underline-offset-4 hover:underline"
            >
              <span>{t("final.whatsapp")}:</span>
              <span dir="ltr" className="num">
                +{contactWhatsapp}
              </span>
            </a>
          </li>
        ) : null}
      </ul>
    </div>
  );
}

function Final() {
  const { t } = useTranslation("marketing");
  return (
    <section aria-labelledby="mk-final" className="mk-section bg-subtle">
      <div className="mk-wrap">
        <h2 id="mk-final" className="mk-section-title max-w-2xl text-fg">
          {t("final.title")}
        </h2>
        <p className="mk-section-lead mt-3 max-w-2xl text-muted">{t("final.lead")}</p>
        <div className="mt-8">
          <Cta place="final" />
        </div>
        <Contact />
      </div>
    </section>
  );
}

/**
 * The product page shown at `/login` when the deployment turns it on (MARKETING_SITE, ADR 0027):
 * a sales showcase whose one action is the staff sign-in. Facts only: the seven rules of the
 * system and what the project proves; no customers, numbers, ratings or prices are claimed.
 */
export function MarketingPage() {
  const { t } = useTranslation("marketing");
  const language = useLanguage();
  useMarketingHead();
  return (
    <div className="mk mk-page-pad min-h-dvh bg-bg text-fg" data-density="comfortable" data-testid="marketing-page">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:start-3 focus:top-3 focus:z-50 focus:rounded-control focus:bg-surface focus:px-4 focus:py-2 focus:text-fg focus:shadow-overlay"
      >
        {t("skip")}
      </a>
      <Header />
      <main id="main">
        <Hero image={shot(`hero-${language}`, HERO_WIDTHS, 800)} />
        <Problem />
        <Cycle />
        <Safety />
        <Roles />
        <Network />
        <PortalSection />
        <Faq />
        <Final />
      </main>
      <footer className="border-t border-border">
        <div className="mk-wrap py-6 text-sm text-muted">{t("footer.text")}</div>
      </footer>
      <div
        className="mk-bar fixed inset-x-0 bottom-0 z-30 border-t border-border bg-surface px-4 pt-3 md:hidden"
        data-testid="mk-bottom-bar"
      >
        <Cta place="bar" />
      </div>
    </div>
  );
}
