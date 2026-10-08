import { Link } from "@tanstack/react-router";
import { CircleSlash, Clock3 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { Can } from "@/components/Can";
import { DateText } from "@/components/DateText";
import { MoneyText } from "@/components/MoneyText";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { usePermission } from "@/lib/auth/hooks";

import { useCurrentShift } from "../api";
import { useNames } from "../lib/use-names";
import { OpenShiftDialog } from "./OpenShiftDialog";

/** The cashier's shift at a glance: open or not, expected cash, pending transfers. */
export function ShiftBar() {
  const { t } = useTranslation("cashier");
  const names = useNames();
  const canOpen = usePermission("payments.open_shift");
  const current = useCurrentShift(canOpen);
  const [openDialog, setOpenDialog] = useState(false);
  if (!canOpen) return null;
  if (current.isPending) return <Skeleton className="h-16 w-full rounded-card" />;
  const report = current.data?.report ?? null;
  const incoming = current.data?.incoming_handovers.length ?? 0;

  return (
    <section
      aria-label={t("shift.barLabel")}
      data-testid="shift-bar"
      data-shift-status={report ? "open" : "none"}
      className="card-surface flex flex-wrap items-center justify-between gap-3 p-3 md:p-4"
    >
      {report ? (
        <>
          <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1">
            <span className="flex items-center gap-2 font-semibold">
              <Clock3 className="size-4 text-primary-strong" aria-hidden="true" />
              <bdi data-testid="shift-number">{report.shift.number}</bdi>
              <Badge variant="success">{t("shift.status.open")}</Badge>
            </span>
            <span className="text-sm text-muted">
              {t("shift.openedAt")} <DateText value={report.shift.opened_at} format="time" />
              {report.shift.till ? ` · ${names.name(report.shift.till)}` : ""}
            </span>
            <span className="text-sm">
              {t("shift.expectedCash")} <MoneyText value={report.expected_cash} />
            </span>
            {report.collection.bank_pending !== "0.00" ? (
              <span className="text-sm text-warning-fg">
                {t("shift.pendingBank")} <MoneyText value={report.collection.bank_pending} />
              </span>
            ) : null}
          </div>
          <Button asChild variant="outline" size="sm">
            <Link to="/cashier/shift">{t("shift.goToClose")}</Link>
          </Button>
        </>
      ) : (
        <>
          <div className="flex min-w-0 items-center gap-2">
            <CircleSlash className="size-4 text-muted" aria-hidden="true" />
            <span className="font-medium">{t("shift.none")}</span>
            <span className="hidden text-sm text-muted sm:inline">{t("shift.noneHint")}</span>
          </div>
          <Button
            size="sm"
            onClick={() => {
              setOpenDialog(true);
            }}
            data-testid="open-shift"
          >
            {t("shift.open")}
          </Button>
        </>
      )}
      {incoming > 0 ? (
        <Can permission="payments.receive_handover">
          <AlertCard variant="info" title={t("handover.incomingTitle", { count: incoming })} className="w-full">
            <Link to="/cashier/shift" className="underline underline-offset-4">
              {t("handover.incomingAction")}
            </Link>
          </AlertCard>
        </Can>
      ) : null}
      <OpenShiftDialog open={openDialog} onOpenChange={setOpenDialog} />
    </section>
  );
}
