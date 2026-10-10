import { Link } from "@tanstack/react-router";
import { KeyRound, Printer } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { AlertCard } from "@/components/AlertCard";
import { Can } from "@/components/Can";
import { DateText } from "@/components/DateText";
import { ReasonDialog } from "@/components/ReasonDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

import { usePatientPortalCodes, useRevokePortalCode } from "../staff-api";

/**
 * On the patient's file at reception: the portal access code's state (never the code), a way
 * to issue and print a new one (which ends the older ones) and to revoke the current one when
 * the slip is lost (ADR 0016 follow-up).
 */
export function PortalAccessCard({ patientId }: { patientId: number }) {
  return (
    <Can permission="portal.issue_access_code">
      <PortalAccessBody patientId={patientId} />
    </Can>
  );
}

function PortalAccessBody({ patientId }: { patientId: number }) {
  const { t } = useTranslation(["portal", "errors"]);
  const language = useLanguage();
  const translateError = useTranslateError();
  const codes = usePatientPortalCodes(patientId);
  const revoke = useRevokePortalCode(patientId);
  const [revoking, setRevoking] = useState(false);
  const active = codes.data?.codes.find((c) => c.state === "active");

  return (
    <section
      aria-labelledby="portal-access-heading"
      className="card-surface flex flex-col gap-3 p-4 md:p-5"
      data-testid="portal-access-card"
    >
      <h2 id="portal-access-heading" className="flex items-center gap-2 text-base font-semibold text-fg">
        <KeyRound className="size-4 text-muted" aria-hidden="true" />
        {t("staff.title")}
      </h2>
      {codes.isError ? (
        <AlertCard variant="danger" title={translateError(codes.error)} />
      ) : codes.isPending ? (
        <Skeleton className="h-12" />
      ) : active ? (
        <div className="flex flex-col gap-1 text-sm" data-testid="portal-access-active">
          <Badge variant="success" className="self-start">
            {t("staff.state.active")}
          </Badge>
          <p className="text-muted">
            {t("staff.issuedBy", {
              name: pickName({ ar: active.created_by.full_name_ar, en: active.created_by.full_name_en }, language),
            })}{" "}
            <DateText value={active.created_at} format="datetime" />
          </p>
          <p className="text-muted">
            {t("staff.validUntil")} <DateText value={active.expires_at} format="date" />
          </p>
        </div>
      ) : (
        <p className="text-sm text-muted" data-testid="portal-access-none">
          {codes.data.has_phone ? t("staff.none") : t("staff.noPhone")}
        </p>
      )}
      <div className="mt-auto flex flex-wrap justify-end gap-2">
        {active ? (
          <Can permission="portal.revoke_access_code">
            <Button
              variant="ghost"
              className="text-danger"
              onClick={() => {
                setRevoking(true);
              }}
              data-testid="portal-access-revoke"
            >
              {t("staff.revoke")}
            </Button>
          </Can>
        ) : null}
        {codes.data?.has_phone ? (
          <Button asChild variant="outline">
            <Link
              to="/patients/$patientId/portal-code"
              params={{ patientId: String(patientId) }}
              data-testid="portal-access-print"
            >
              <Printer aria-hidden="true" />
              {active ? t("staff.reissue") : t("staff.issue")}
            </Link>
          </Button>
        ) : null}
      </div>
      <ReasonDialog
        open={revoking}
        onOpenChange={setRevoking}
        title={t("staff.revokeTitle")}
        description={t("staff.revokeDescription")}
        reasons={[]}
        destructive
        confirmLabel={t("staff.revoke")}
        onSubmit={async ({ note }) => {
          if (!active) return;
          await revoke.mutateAsync({ codeId: active.id, note });
          toast.success(t("staff.revokedToast"));
        }}
      />
    </section>
  );
}
