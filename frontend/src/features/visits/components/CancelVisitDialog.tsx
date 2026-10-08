import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { AlertCard } from "@/components/AlertCard";
import { ReasonDialog } from "@/components/ReasonDialog";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { usePermission } from "@/lib/auth/hooks";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

import { useCancelVisit, useVisitOptions } from "../api";

export interface CancelVisitTarget {
  id: number;
  number: string;
  /** Open lines on an approved invoice: cancelling issues a credit note (server flag). */
  billed: boolean;
}

export interface CancelVisitDialogProps {
  /** The visit to cancel; null closes the dialog. */
  visit: CancelVisitTarget | null;
  onOpenChange: (open: boolean) => void;
}

/**
 * Visit cancellation with a reason (FEATURES 2.7, invariant 4). Paid lines are credited by the
 * server and the money becomes refundable patient credit; the dialog only collects the reason.
 * A billed visit needs a supervisor who approves credit notes: anyone else is told so before
 * typing a reason (the server refuses them anyway).
 */
export function CancelVisitDialog({ visit, onOpenChange }: CancelVisitDialogProps) {
  const { t } = useTranslation(["visits", "common"]);
  const language = useLanguage();
  const options = useVisitOptions();
  const cancel = useCancelVisit();
  const canApproveCredit = usePermission("billing.approve_credit_note");
  const reasons = (options.data?.cancel_reasons ?? []).map((r) => ({
    code: r.code,
    label: pickName({ ar: r.label_ar, en: r.label_en }, language),
  }));

  if (visit?.billed && !canApproveCredit) {
    return (
      <Dialog open onOpenChange={onOpenChange}>
        <DialogContent data-testid="cancel-needs-supervisor">
          <DialogHeader>
            <DialogTitle>{t("cancel.title")}</DialogTitle>
            <DialogDescription>
              {t("cancel.visit")} <bdi className="tabular font-semibold text-fg">{visit.number}</bdi>
            </DialogDescription>
          </DialogHeader>
          <AlertCard variant="warning" title={t("cancel.needsSupervisorTitle")}>
            {t("cancel.needsSupervisor")}
          </AlertCard>
          <DialogFooter>
            <DialogClose asChild>
              <Button variant="outline">{t("common:actions.close")}</Button>
            </DialogClose>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  }

  return (
    <ReasonDialog
      open={visit !== null}
      onOpenChange={onOpenChange}
      title={t("cancel.title")}
      description={visit?.billed ? t("cancel.descriptionBilled") : t("cancel.description")}
      reasons={reasons}
      noteRequired={false}
      destructive
      confirmLabel={t("cancel.confirm")}
      onSubmit={async ({ code, note }) => {
        if (!visit) return;
        await cancel.mutateAsync({ id: visit.id, body: { reason_code: code, note } });
        toast.success(t("cancel.done", { number: visit.number }));
      }}
    >
      {visit ? (
        <p className="text-sm text-muted">
          {t("cancel.visit")} <bdi className="tabular font-semibold text-fg">{visit.number}</bdi>
        </p>
      ) : null}
    </ReasonDialog>
  );
}
