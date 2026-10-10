import { KeyRound } from "lucide-react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { Can } from "@/components/Can";
import { Button } from "@/components/ui/button";
import { useTranslateError } from "@/lib/api/translate-error";
import { formatDate } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";
import { cn } from "@/lib/utils";

import { useIssuePortalCode } from "../api";

/**
 * On the cashier's receipt: issue a portal access code for the receipt's patient and print it
 * with the sign-in instructions (FEATURES 15.2). The code is shown once; a new one revokes the
 * earlier codes of the file.
 */
export function ReceiptPortalCode({ paymentId, compact = false }: { paymentId: number; compact?: boolean }) {
  const { t } = useTranslation(["portal", "errors"]);
  const translateError = useTranslateError();
  const language = useLanguage();
  const issue = useIssuePortalCode();
  const issued = issue.data;

  return (
    <Can permission="portal.issue_access_code">
      <div
        className={cn("flex flex-col gap-2 border-t border-border pt-3", issued ? "" : "print:hidden")}
        data-testid="receipt-portal"
      >
        {issued ? (
          <div className="flex flex-col items-center gap-1 text-center" data-testid="receipt-portal-code">
            <p className="font-semibold">{t("code.title")}</p>
            <p className="text-xs">
              {t("code.fileNo")}: <bdi>{issued.file_no}</bdi>
            </p>
            <p className="text-xs">{t("code.code")}</p>
            <bdi
              dir="ltr"
              className={cn("tabular font-bold tracking-widest", compact ? "text-xl" : "text-2xl")}
              data-testid="receipt-portal-code-value"
            >
              {issued.code}
            </bdi>
            <p className="text-xs">{t("code.expires", { date: formatDate(issued.expires_at, language, "date") })}</p>
            <p className="text-xs text-pretty">{t("code.howTo", { url: `${window.location.host}/portal` })}</p>
          </div>
        ) : (
          <p className="text-xs text-muted">{t("code.description")}</p>
        )}
        {issue.isError ? <AlertCard variant="danger" title={translateError(issue.error)} live /> : null}
        <Button
          type="button"
          variant={issued ? "outline" : "soft"}
          size="sm"
          className="self-center print:hidden"
          loading={issue.isPending}
          data-testid="receipt-portal-issue"
          onClick={() => issue.mutate(paymentId)}
        >
          <KeyRound aria-hidden="true" />
          {issued ? t("code.reissue") : t("code.issue")}
        </Button>
      </div>
    </Can>
  );
}
