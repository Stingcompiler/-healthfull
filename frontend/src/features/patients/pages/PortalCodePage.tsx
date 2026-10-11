import { Link, useParams } from "@tanstack/react-router";
import { ArrowLeft, KeyRound } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { PrintFrame } from "@/features/cashier/components/PrintFrame";
import { useTranslateError } from "@/lib/api/translate-error";
import { formatDate } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";
import { cn } from "@/lib/utils";
import { useIssuePatientPortalCode, usePatientPortalCodes } from "@/portal/staff-api";

/**
 * Portal access slip from the patient's file (ADR 0016 follow-up): reception issues a new code,
 * which ends the older ones, and prints it on 80 mm or A4 with the sign-in instructions. The
 * code is shown once; leaving the page loses it (issue another).
 */
export function PortalCodePage() {
  const { t } = useTranslation(["portal", "patients", "errors"]);
  const language = useLanguage();
  const translateError = useTranslateError();
  const { patientId: raw } = useParams({ strict: false });
  const patientId = Number(raw);
  const codes = usePatientPortalCodes(patientId);
  const issue = useIssuePatientPortalCode(patientId);
  const [confirming, setConfirming] = useState(false);
  const slip = issue.data;
  const hasActive = codes.data?.codes.some((c) => c.state === "active") ?? false;

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader
        title={t("staff.slipTitle")}
        description={t("staff.slipDescription")}
        icon={<KeyRound />}
        actions={
          <Button asChild variant="outline" className="print:hidden">
            <Link to="/patients/$patientId" params={{ patientId: String(patientId) }}>
              <ArrowLeft aria-hidden="true" className="rtl:-scale-x-100" />
              {t("staff.backToFile")}
            </Link>
          </Button>
        }
      />
      {codes.isError ? <AlertCard variant="danger" title={translateError(codes.error)} /> : null}
      {issue.isError ? <AlertCard variant="danger" title={translateError(issue.error)} live /> : null}
      {codes.data && !codes.data.has_phone ? <AlertCard variant="warning" title={t("staff.noPhone")} /> : null}
      {!slip ? (
        <div className="card-surface flex flex-col items-start gap-3 p-4 md:p-5 print:hidden">
          <p className="text-sm text-pretty text-muted">
            {hasActive ? t("staff.replaceWarning") : t("code.description")}
          </p>
          <Button
            onClick={() => {
              if (hasActive) setConfirming(true);
              else issue.mutate();
            }}
            loading={issue.isPending}
            disabled={!codes.data?.has_phone}
            data-testid="portal-code-issue"
          >
            <KeyRound aria-hidden="true" />
            {t("staff.issueNow")}
          </Button>
        </div>
      ) : (
        <PrintFrame>
          {(format) => (
            <div
              className={cn(
                "flex flex-col items-center gap-2 text-center",
                format === "thermal" ? "text-sm" : "mx-auto max-w-md text-base",
              )}
              data-testid="portal-slip"
            >
              <p className="font-semibold">{t("code.title")}</p>
              <p className="text-pretty break-words">
                {pickName({ ar: slip.full_name_ar, en: slip.full_name_en }, language)}
              </p>
              <p>
                {t("code.fileNo")}: <bdi>{slip.file_no}</bdi>
              </p>
              <p className="text-xs">{t("code.code")}</p>
              <bdi dir="ltr" className="tabular text-2xl font-bold tracking-widest" data-testid="portal-slip-code">
                {slip.code}
              </bdi>
              <p className="text-xs">{t("code.expires", { date: formatDate(slip.expires_at, language, "date") })}</p>
              <p className="text-xs text-pretty">{t("code.howTo", { url: `${window.location.host}/portal` })}</p>
            </div>
          )}
        </PrintFrame>
      )}
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={t("staff.replaceTitle")}
        description={t("staff.replaceWarning")}
        confirmLabel={t("staff.issueNow")}
        onConfirm={() => {
          issue.mutate();
        }}
      />
    </div>
  );
}
