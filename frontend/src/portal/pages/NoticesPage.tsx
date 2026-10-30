import { Link } from "@tanstack/react-router";
import { BellOff, CalendarDays, CheckCheck, FlaskConical } from "lucide-react";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { ChevronNext } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";
import { formatDate } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";
import type { Language } from "@/lib/preferences";
import { cn } from "@/lib/utils";

import { useMarkAllNoticesRead, useMarkNoticeRead, useNotices } from "../api";
import { PortalPage, Pill } from "../components/PortalPage";
import { usePick } from "../lib/ui";
import type { PortalNotice } from "../types";

type Pick = ReturnType<typeof usePick>;

function text(value: string | boolean | undefined): string {
  return typeof value === "string" ? value : "";
}

/** The notice's sentence in the UI language, from its kind and payload (no server text). */
function noticeBody(t: TFunction<"portal">, notice: PortalNotice, language: Language, pick: Pick): string[] {
  const p = notice.payload;
  if (notice.kind === "result_published") {
    const test = pick(text(p.test_ar), text(p.test_en));
    return [t(p.amended === true ? "notices.body.result_amended" : "notices.body.result_published", { test })];
  }
  const vars = {
    doctor: pick(text(p.doctor_ar), text(p.doctor_en)),
    time: p.starts_at ? formatDate(text(p.starts_at), language, "datetime") : "",
  };
  const lines: string[] = [];
  if (notice.kind === "booking_cancelled") {
    lines.push(t(p.by_you === true ? "notices.body.booking_cancelled_by_you" : "notices.body.booking_cancelled", vars));
  } else {
    lines.push(t(`notices.body.${notice.kind}`, vars));
  }
  const reason = pick(text(p.reason_ar), text(p.reason_en));
  if (reason) lines.push(t("notices.reason", { reason }));
  if (notice.kind === "booking_rescheduled" && p.awaiting_approval === true) lines.push(t("notices.awaitingHint"));
  return lines;
}

function NoticeRow({ notice }: { notice: PortalNotice }) {
  const { t } = useTranslation("portal");
  const language = useLanguage();
  const pick = usePick();
  const markRead = useMarkNoticeRead();
  const unread = notice.read_at === null;
  const isResult = notice.kind === "result_published";
  const Icon = isResult ? FlaskConical : CalendarDays;
  const onOpen = () => {
    if (unread) markRead.mutate(notice.id);
  };
  const [first, ...rest] = noticeBody(t, notice, language, pick);
  const linkClass =
    "inline-flex min-h-11 w-fit items-center gap-1 rounded-control px-1 text-sm font-medium text-primary-strong focus-ring";

  return (
    <li
      className={cn("flex gap-3 px-4 py-3", unread && "bg-primary-soft/40")}
      data-testid="notice-row"
      data-kind={notice.kind}
      data-unread={unread ? "true" : undefined}
    >
      <Icon className="mt-0.5 size-5 shrink-0 text-muted" aria-hidden="true" />
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-fg">{t(`notices.kind.${notice.kind}`)}</h2>
          {unread ? (
            <Pill tone="info" testId="notice-new">
              {t("notices.new")}
            </Pill>
          ) : null}
        </div>
        <p className="text-sm text-pretty break-words text-fg">{first}</p>
        {rest.map((line) => (
          <p key={line} className="text-sm text-pretty break-words text-muted">
            {line}
          </p>
        ))}
        <p className="text-xs text-muted">
          <DateText value={notice.created_at} format="datetime" />
        </p>
        <div className="flex flex-wrap items-center gap-x-3">
          {notice.result_line_id !== null ? (
            <Link
              to="/portal/results/$lineId"
              params={{ lineId: String(notice.result_line_id) }}
              className={linkClass}
              onClick={onOpen}
              data-testid="notice-open"
            >
              {t("notices.openResult")}
              <ChevronNext className="size-4" aria-hidden="true" />
            </Link>
          ) : notice.appointment_id !== null ? (
            <Link to="/portal/appointments" className={linkClass} onClick={onOpen} data-testid="notice-open">
              {t("notices.openAppointments")}
              <ChevronNext className="size-4" aria-hidden="true" />
            </Link>
          ) : null}
          {unread ? (
            <Button
              variant="ghost"
              size="sm"
              disabled={markRead.isPending}
              onClick={onOpen}
              data-testid="notice-mark-read"
            >
              {t("notices.markRead")}
            </Button>
          ) : null}
        </div>
      </div>
    </li>
  );
}

/** The patient's inbox (ADR 0029 I): booking changes and published results, newest first. */
export function NoticesPage() {
  const { t } = useTranslation(["portal", "errors"]);
  const translateError = useTranslateError();
  const notices = useNotices();
  const markAll = useMarkAllNoticesRead();
  const unread = notices.data?.unread ?? 0;

  return (
    <PortalPage
      title={t("notices.title")}
      description={t("notices.description")}
      actions={
        unread > 0 ? (
          <Button
            variant="outline"
            size="sm"
            loading={markAll.isPending}
            onClick={() => {
              markAll.mutate();
            }}
            data-testid="notices-mark-all"
          >
            <CheckCheck aria-hidden="true" />
            {t("notices.markAll")}
          </Button>
        ) : undefined
      }
    >
      {notices.isPending ? (
        <Skeleton className="h-40" />
      ) : notices.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(notices.error)}
        </AlertCard>
      ) : notices.data.items.length === 0 ? (
        <EmptyState icon={<BellOff />} title={t("notices.none")} description={t("notices.noneHint")} />
      ) : (
        <ul className="card-surface divide-y divide-border overflow-hidden" data-testid="notices-list">
          {notices.data.items.map((n) => (
            <NoticeRow key={n.id} notice={n} />
          ))}
        </ul>
      )}
    </PortalPage>
  );
}
