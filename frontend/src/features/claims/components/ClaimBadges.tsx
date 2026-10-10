import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";

import type { ClaimLineStage, ClaimStatus, PayerPaymentStanding } from "../types";

type Variant = "neutral" | "info" | "warning" | "success" | "danger" | "outline" | "soft";

const CLAIM_VARIANT: Record<ClaimStatus, Variant> = {
  draft: "neutral",
  submitted: "info",
  responded: "warning",
  closed: "success",
  void: "outline",
};

const STAGE_VARIANT: Record<ClaimLineStage, Variant> = {
  claimed: "info",
  accepted: "soft",
  partially_accepted: "warning",
  rejected: "danger",
  paid: "success",
  rebilled: "neutral",
  written_off: "neutral",
  voided: "outline",
};

const STANDING_VARIANT: Record<PayerPaymentStanding, Variant> = {
  bank: "success",
  cash: "success",
  cheque_pending: "warning",
  cheque_cleared: "success",
  reversed: "danger",
};

/** A claim batch's status (draft, submitted, answered, closed, void). */
export function ClaimStatusBadge({ status }: { status: ClaimStatus }) {
  const { t } = useTranslation("claims");
  return (
    <Badge variant={CLAIM_VARIANT[status]} data-status={status}>
      {t(`status.${status}`)}
    </Badge>
  );
}

/** Where a claim line stands in the payer cycle (claimed, accepted, paid, rebilled...). */
export function ClaimStageBadge({ stage }: { stage: ClaimLineStage }) {
  const { t } = useTranslation("claims");
  return (
    <Badge variant={STAGE_VARIANT[stage]} data-stage={stage}>
      {t(`stage.${stage}`)}
    </Badge>
  );
}

/** Where a payer payment's money is: bank, a drawer, a cheque waiting to clear, or reversed. */
export function PaymentStandingBadge({ standing }: { standing: PayerPaymentStanding }) {
  const { t } = useTranslation("claims");
  return (
    <Badge variant={STANDING_VARIANT[standing]} data-standing={standing}>
      {t(`standing.${standing}`)}
    </Badge>
  );
}
