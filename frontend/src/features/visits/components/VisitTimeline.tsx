import {
  Ban,
  BedDouble,
  CircleCheck,
  ClipboardList,
  DoorClosed,
  DoorOpen,
  FileCheck2,
  FlaskConical,
  HandCoins,
  Pill,
  ReceiptText,
  Undo2,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { DateText } from "@/components/DateText";
import { MoneyText } from "@/components/MoneyText";
import { Skeleton } from "@/components/ui/skeleton";
import { QueryErrorAlert } from "@/features/patients/components/QueryErrorAlert";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";
import { translateKey } from "@/lib/validation";

import { useVisitTimeline } from "../api";
import type { TimelineEvent } from "../types";

const ICONS: Record<string, LucideIcon> = {
  visit_created: DoorOpen,
  line_ordered: ClipboardList,
  line_performed: CircleCheck,
  line_cancelled: Ban,
  result_approved: FlaskConical,
  dispensed: Pill,
  invoice_approved: ReceiptText,
  payment_allocated: HandCoins,
  credit_note: FileCheck2,
  refund: Undo2,
  admitted: BedDouble,
  discharged: BedDouble,
  visit_closed: DoorClosed,
  visit_cancelled: Ban,
};

const KNOWN = new Set(Object.keys(ICONS));

function text(detail: Record<string, unknown>, key: string): string {
  const value = detail[key];
  return typeof value === "string" ? value : "";
}

/** Everything linked to a visit, oldest first (FEATURES 2.4). Money shows only when the API sends it. */
export function VisitTimeline({ visitId }: { visitId: number }) {
  const { t } = useTranslation("visits");
  const timeline = useVisitTimeline(visitId, true);

  if (timeline.isPending) {
    return (
      <div className="grid gap-2" role="status" aria-label={t("timeline.loading")}>
        <Skeleton className="h-10" />
        <Skeleton className="h-10" />
      </div>
    );
  }
  if (timeline.isError) {
    return (
      <QueryErrorAlert
        title={t("timeline.loadFailed")}
        error={timeline.error}
        onRetry={() => void timeline.refetch()}
        retrying={timeline.isFetching}
      />
    );
  }
  const events = timeline.data;
  if (events.length === 0) return <p className="text-sm text-muted">{t("timeline.empty")}</p>;
  return (
    <ol className="relative grid gap-3 border-s border-border ps-4" aria-label={t("timeline.title")}>
      {events.map((e) => (
        <TimelineRow key={`${e.kind}-${String(e.ref_id)}-${e.at}`} event={e} />
      ))}
    </ol>
  );
}

function TimelineRow({ event }: { event: TimelineEvent }) {
  const { t } = useTranslation();
  const language = useLanguage();
  const Icon = ICONS[event.kind] ?? ClipboardList;
  const detail = event.detail;
  const service = pickName({ ar: text(detail, "service_name_ar"), en: text(detail, "service_name_en") }, language);
  const number = text(detail, "number");
  const amount = text(detail, "amount") || text(detail, "patient_total");
  const actor = event.actor ? pickName({ ar: event.actor.name_ar, en: event.actor.name_en }, language) : "";
  return (
    <li className="relative min-w-0">
      <span
        aria-hidden="true"
        className="absolute -start-[1.6rem] top-0.5 flex size-6 items-center justify-center rounded-full border border-border bg-surface text-muted [&_svg]:size-3.5"
      >
        <Icon />
      </span>
      <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <span className="text-sm font-medium text-fg">
          {KNOWN.has(event.kind) ? translateKey(t, `visits:timeline.kind.${event.kind}`) : event.kind}
        </span>
        {service ? <span className="text-sm break-words text-fg">{service}</span> : null}
        {number ? <bdi className="tabular text-sm text-muted">{number}</bdi> : null}
        {amount ? <MoneyText value={amount} className="text-sm" /> : null}
      </div>
      <p className="text-xs text-muted">
        <DateText value={event.at} format="datetime" />
        {actor ? ` · ${actor}` : null}
      </p>
    </li>
  );
}
