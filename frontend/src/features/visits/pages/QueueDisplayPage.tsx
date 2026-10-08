import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { Megaphone, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { formatDate, formatNumber } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";
import { useDocumentTitle } from "@/lib/hooks/use-document-title";
import { cn } from "@/lib/utils";

import { useVisitOptions, useWaitingRoom } from "../api";
import { ALL } from "../lib";
import type { DisplayEntry } from "../types";

/**
 * Waiting-room screen (FEATURES 2.3) for a TV in the waiting area: the tokens being called in
 * large type and the paid tokens still waiting. Names are abbreviated by the server (privacy).
 * It covers the whole viewport (kiosk) and refreshes itself every few seconds.
 */
export function QueueDisplayPage() {
  const { t } = useTranslation("visits");
  const language = useLanguage();
  const navigate = useNavigate();
  const search: { department?: number } = useSearch({ strict: false });
  const departmentId = typeof search.department === "number" ? search.department : null;
  const options = useVisitOptions();
  const room = useWaitingRoom(departmentId);
  const clock = useClock();
  useDocumentTitle(t("display.title"));

  const department = options.data?.departments.find((d) => d.id === departmentId);
  const serving = room.data?.serving ?? [];
  const waiting = room.data?.waiting ?? [];
  const [latest, ...earlier] = serving;
  const n = (value: number) => formatNumber(value, language);

  return (
    <div className="fixed inset-0 z-40 flex flex-col overflow-y-auto bg-bg text-fg" data-testid="queue-display">
      <header className="flex flex-wrap items-center gap-3 border-b-2 border-border-strong bg-surface px-4 py-3 md:px-8">
        <h1 className="min-w-0 flex-1 text-2xl font-bold break-words md:text-4xl">
          {department ? pickName({ ar: department.name_ar, en: department.name_en }, language) : t("display.title")}
        </h1>
        <p className="tabular text-xl font-semibold md:text-3xl" aria-live="off">
          {formatDate(clock, language, "time")}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <Select
            value={departmentId ? String(departmentId) : ALL}
            onValueChange={(v) => {
              void navigate({
                to: "/queue/display",
                search: v === ALL ? {} : { department: Number(v) },
                replace: true,
              });
            }}
          >
            <SelectTrigger className="w-44" aria-label={t("board.department")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>{t("board.allDepartments")}</SelectItem>
              {(options.data?.departments ?? []).map((d) => (
                <SelectItem key={d.id} value={String(d.id)}>
                  {pickName({ ar: d.name_ar, en: d.name_en }, language)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <LanguageSwitcher />
          <Button asChild variant="outline" size="sm">
            <Link to="/queue" aria-label={t("display.exit")}>
              <X aria-hidden="true" />
              <span className="max-sm:sr-only">{t("display.exit")}</span>
            </Link>
          </Button>
        </div>
      </header>

      <div className="grid flex-1 content-start gap-4 p-4 md:grid-cols-[3fr_2fr] md:gap-6 md:p-8">
        <section aria-labelledby="display-now" className="flex min-w-0 flex-col gap-4">
          <h2 id="display-now" className="flex items-center gap-2 text-xl font-bold md:text-3xl">
            <Megaphone className="size-6 md:size-8" aria-hidden="true" />
            {t("display.nowServing")}
          </h2>
          <div aria-live="polite" aria-atomic="true">
            {latest ? (
              <CalledCard entry={latest} highlight />
            ) : (
              <p className="rounded-card border-2 border-dashed border-border-strong p-8 text-center text-xl text-muted md:text-3xl">
                {t("display.nobodyCalled")}
              </p>
            )}
          </div>
          {earlier.length > 0 ? (
            <ul className="grid gap-3 sm:grid-cols-2" aria-label={t("display.recentlyCalled")}>
              {earlier.slice(0, 6).map((e) => (
                <li key={`${String(e.token_no)}-${e.department.id}`}>
                  <CalledCard entry={e} />
                </li>
              ))}
            </ul>
          ) : null}
        </section>

        <section aria-labelledby="display-waiting" className="flex min-w-0 flex-col gap-4">
          <h2 id="display-waiting" className="text-xl font-bold md:text-3xl">
            {t("display.waiting", { count: waiting.length, n: n(waiting.length) })}
          </h2>
          {waiting.length > 0 ? (
            <ol className="grid grid-cols-2 gap-3 lg:grid-cols-3">
              {waiting.slice(0, 18).map((e) => (
                <li
                  key={`${String(e.token_no)}-${e.department.id}`}
                  className="flex min-w-0 flex-col items-center rounded-card border-2 border-border-strong bg-surface p-3"
                >
                  <span className="tabular text-3xl font-bold md:text-5xl">{n(e.token_no)}</span>
                  <span className="text-center text-base break-words md:text-xl">
                    {language === "ar" ? e.name_ar : e.name_en}
                  </span>
                </li>
              ))}
            </ol>
          ) : (
            <p className="text-lg text-muted md:text-2xl">{t("display.noneWaiting")}</p>
          )}
        </section>
      </div>
    </div>
  );
}

function CalledCard({ entry, highlight = false }: { entry: DisplayEntry; highlight?: boolean }) {
  const { t } = useTranslation("visits");
  const language = useLanguage();
  const place = entry.room
    ? pickName({ ar: entry.room.name_ar, en: entry.room.name_en }, language)
    : entry.doctor
      ? pickName({ ar: entry.doctor.name_ar, en: entry.doctor.name_en }, language)
      : pickName({ ar: entry.department.name_ar, en: entry.department.name_en }, language);
  return (
    <div
      data-testid={highlight ? "display-current" : undefined}
      className={cn(
        "flex min-w-0 flex-wrap items-center gap-4 rounded-card border-4 p-4 md:p-6",
        highlight ? "border-primary bg-primary text-primary-fg" : "border-border-strong bg-surface text-fg",
      )}
    >
      <span
        className={cn("tabular leading-none font-black", highlight ? "text-7xl md:text-9xl" : "text-4xl md:text-6xl")}
      >
        {formatNumber(entry.token_no, language)}
      </span>
      <span className="flex min-w-0 flex-1 flex-col gap-1">
        <span className={cn("font-bold break-words", highlight ? "text-3xl md:text-5xl" : "text-xl md:text-3xl")}>
          {language === "ar" ? entry.name_ar : entry.name_en}
        </span>
        <span className={cn("break-words", highlight ? "text-xl md:text-3xl" : "text-base md:text-xl")}>
          {entry.status === "in_progress" ? t("display.withDoctor", { place }) : t("display.goTo", { place })}
        </span>
      </span>
    </div>
  );
}

function useClock(): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => {
      setNow(new Date());
    }, 15_000);
    return () => {
      window.clearInterval(id);
    };
  }, []);
  return now;
}
