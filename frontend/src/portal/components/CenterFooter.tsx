import { Link } from "@tanstack/react-router";
import { ExternalLink } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { ThemeSwitcher } from "@/components/ThemeSwitcher";
import { useCenterPage } from "@/lib/center/api";
import { useCenterName, useOpenStatusText } from "@/lib/center/hooks";
import { useLanguage } from "@/lib/i18n-hooks";
import { signInPath } from "@/lib/site";
import { cn } from "@/lib/utils";
import { formatClock, weekdayName } from "@/lib/weekdays";

import { centerTasks, POLICIES_ID, stickyBar, summarizeHours } from "../lib/center-tasks";
import { usePick } from "../lib/ui";
import { useCenterTaskInput } from "../lib/use-center-tasks";
import { CenterMark } from "./CenterMark";

/** The vendor's site, a plain link (nothing is fetched from it). */
const VENDOR_URL = "https://stingdev.pro";
const VENDOR_HOST = "stingdev.pro";

const linkClass =
  "inline-flex min-h-11 items-center rounded-control text-sm text-fg underline-offset-4 hover:text-primary-strong hover:underline focus-ring md:min-h-9";

function Column({ title, children, testId }: { title: string; children: ReactNode; testId?: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-2" data-testid={testId}>
      <h2 className="text-sm font-semibold text-fg">{title}</h2>
      {children}
    </div>
  );
}

/**
 * The center website's footer (D-0022): name and logo, contact, an hours summary, quick links,
 * language and theme, the copyright and the vendor line. Every block appears only with its data;
 * on phones the footer leaves room for the floating action bar.
 */
export function CenterFooter() {
  const { t } = useTranslation("portal");
  const language = useLanguage();
  const pick = usePick();
  const identityName = useCenterName();
  const page = useCenterPage().data;
  const input = useCenterTaskInput(page);
  const tasks = centerTasks(input);
  const reserveBar = input.signedIn || stickyBar(input) !== null;
  const status = useOpenStatusText(page?.today, page?.hours ?? []);
  const name = (page ? pick(page.name_ar, page.name_en) : "") || identityName;
  const runs = page ? summarizeHours(page.hours) : [];
  const hasPolicies = Boolean(
    page && (pick(page.privacy_ar, page.privacy_en) || pick(page.cancellation_policy_ar, page.cancellation_policy_en)),
  );
  const hasContact = Boolean(page && (page.address || page.phone_uri || page.whatsapp || page.email));
  const year = new Date().getFullYear();

  return (
    <footer
      className={cn(
        "mt-10 border-t border-border bg-surface print:hidden",
        reserveBar ? "pb-[calc(6rem+env(safe-area-inset-bottom))] md:pb-0" : "pb-[env(safe-area-inset-bottom)]",
      )}
      aria-label={t("center.footer.label")}
      data-testid="center-footer"
    >
      <div className="mx-auto grid w-full max-w-[75rem] gap-8 px-4 py-10 sm:grid-cols-2 md:px-6 lg:grid-cols-[minmax(0,1.3fr)_repeat(3,minmax(0,1fr))] lg:px-8">
        <div className="flex min-w-0 flex-col gap-3 sm:col-span-2 lg:col-span-1">
          <div className="flex items-center gap-3">
            <CenterMark logoUrl={page?.logo_url} name={name} className="size-11 text-base" testId="footer-monogram" />
            <p className="min-w-0 text-base font-bold text-balance break-words text-fg">{name}</p>
          </div>
          <p className="max-w-sm text-sm text-pretty text-muted">{t("privacy")}</p>
        </div>

        {hasContact && page ? (
          <Column title={t("center.footer.contact")} testId="footer-contact">
            {page.address ? <p className="text-sm text-pretty text-muted">{page.address}</p> : null}
            <ul className="flex flex-col">
              {page.phone_uri ? (
                <li>
                  <a href={page.phone_uri} className={linkClass}>
                    <span className="num">{page.phone}</span>
                  </a>
                </li>
              ) : null}
              {page.whatsapp ? (
                <li>
                  <a href={`https://wa.me/${page.whatsapp}`} rel="noopener noreferrer" className={linkClass}>
                    {t("center.whatsapp")}&nbsp;<span className="num">+{page.whatsapp}</span>
                  </a>
                </li>
              ) : null}
              {page.email ? (
                <li>
                  <a href={`mailto:${page.email}`} className={cn(linkClass, "break-all")}>
                    <span dir="ltr">{page.email}</span>
                  </a>
                </li>
              ) : null}
            </ul>
          </Column>
        ) : null}

        {runs.length > 0 ? (
          <Column title={t("center.footer.hours")} testId="footer-hours">
            {status ? <p className="text-sm font-medium text-fg">{status}</p> : null}
            <dl className="flex flex-col gap-1 text-sm">
              {runs.map((run) => (
                <div key={run.from} className="flex flex-wrap gap-x-2">
                  <dt className="text-muted">
                    {run.from === run.to
                      ? weekdayName(run.from, language, "short")
                      : t("center.footer.range", {
                          from: weekdayName(run.from, language, "short"),
                          to: weekdayName(run.to, language, "short"),
                        })}
                  </dt>
                  <dd className="tabular text-fg">
                    {t("center.span", {
                      from: formatClock(run.opens, language),
                      to: formatClock(run.closes, language),
                    })}
                  </dd>
                </div>
              ))}
            </dl>
          </Column>
        ) : null}

        <Column title={t("center.footer.links")} testId="footer-links">
          <ul className="flex flex-col">
            {tasks.book ? (
              <li>
                <Link to={tasks.book} className={linkClass} data-testid="footer-book">
                  {t("center.bookOnline")}
                </Link>
              </li>
            ) : null}
            {tasks.myBooking ? (
              <li>
                <Link to="/portal/booking" className={linkClass} data-testid="footer-my-booking">
                  {t("center.tasks.myBooking")}
                </Link>
              </li>
            ) : null}
            {tasks.signIn ? (
              <li>
                <Link
                  to={input.signedIn ? "/portal/home" : "/portal/sign-in"}
                  className={linkClass}
                  data-testid="footer-sign-in"
                >
                  {input.signedIn ? t("center.openFile") : t("center.signIn")}
                </Link>
              </li>
            ) : null}
            {hasPolicies ? (
              <li>
                <a href={`#${POLICIES_ID}`} className={linkClass} data-testid="footer-policies">
                  {t("center.policies.label")}
                </a>
              </li>
            ) : null}
            {input.signedIn ? null : (
              <li>
                <Link to={signInPath()} className={linkClass}>
                  {t("staffLink")}
                </Link>
              </li>
            )}
          </ul>
        </Column>
      </div>

      <div className="border-t border-border">
        <div className="mx-auto flex w-full max-w-[75rem] flex-col gap-3 px-4 py-5 md:flex-row md:items-center md:justify-between md:px-6 lg:px-8">
          <div className="flex flex-col gap-1 text-xs text-muted sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-4">
            <p>{t("center.footer.copyright", { year, name })}</p>
            <p>
              <a
                href={VENDOR_URL}
                target="_blank"
                rel="noopener"
                className="inline-flex min-h-11 items-center gap-1.5 rounded-control font-medium text-fg underline-offset-4 focus-ring hover:text-primary-strong hover:underline md:min-h-8"
                data-testid="footer-powered-by"
              >
                {t("center.footer.poweredBy")}
                <span aria-hidden="true">·</span>
                <span dir="ltr">{VENDOR_HOST}</span>
                <ExternalLink className="size-3.5" aria-hidden="true" />
                <span className="sr-only">{t("center.footer.newTab")}</span>
              </a>
            </p>
          </div>
          <div
            className="-ms-2.5 flex items-center gap-1 md:ms-0"
            aria-label={t("center.footer.settings")}
            role="group"
          >
            <LanguageSwitcher />
            <ThemeSwitcher labelled />
          </div>
        </div>
      </div>
    </footer>
  );
}
