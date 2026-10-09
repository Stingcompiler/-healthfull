import { Link } from "@tanstack/react-router";
import { Clock3, Printer } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";

import { useCurrentShift } from "../api";
import { CashierNav } from "../components/CashierNav";
import { CloseShiftForm } from "../components/CloseShiftForm";
import { HandoverPanel, IncomingHandovers } from "../components/HandoverPanel";
import { OpenShiftDialog } from "../components/OpenShiftDialog";
import { ShiftReportView } from "../components/ShiftReportView";
import type { ShiftReport } from "../types";

/** The cashier's own shift: live report, handovers, and the close with counted cash (7.1-7.6). */
export function ShiftPage() {
  const { t } = useTranslation(["cashier", "errors"]);
  const translateError = useTranslateError();
  const current = useCurrentShift();
  const [closed, setClosed] = useState<ShiftReport | null>(null);
  const [openDialog, setOpenDialog] = useState(false);
  const report = current.data?.report ?? null;

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader title={t("shiftPage.title")} description={t("shiftPage.description")} icon={<Clock3 />} />
      <CashierNav />
      {current.isPending ? (
        <Skeleton className="h-64 w-full rounded-card" />
      ) : current.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(current.error)}
        </AlertCard>
      ) : (
        <>
          <IncomingHandovers handovers={current.data.incoming_handovers} />
          {closed ? (
            <>
              <AlertCard
                variant="success"
                title={t("close.doneTitle", { number: closed.shift.number })}
                live
                action={
                  <Button asChild variant="outline" size="sm">
                    <Link to="/cashier/shifts/$shiftId" params={{ shiftId: String(closed.shift.id) }}>
                      <Printer aria-hidden="true" />
                      {t("close.viewReport")}
                    </Link>
                  </Button>
                }
              >
                {t("close.doneBody")}
              </AlertCard>
              <ShiftReportView report={closed} />
            </>
          ) : report ? (
            <>
              <ShiftReportView report={report} />
              <div className="grid min-w-0 gap-4 lg:grid-cols-2">
                <HandoverPanel report={report} />
                <CloseShiftForm report={report} onClosed={setClosed} />
              </div>
            </>
          ) : (
            <EmptyState
              icon={<Clock3 />}
              title={t("shift.none")}
              description={t("shift.noneHint")}
              action={
                <Button
                  onClick={() => {
                    setOpenDialog(true);
                  }}
                  data-testid="open-shift"
                >
                  {t("shift.open")}
                </Button>
              }
            />
          )}
        </>
      )}
      <OpenShiftDialog
        open={openDialog}
        onOpenChange={(o) => {
          setOpenDialog(o);
          if (!o) setClosed(null);
        }}
      />
    </div>
  );
}
