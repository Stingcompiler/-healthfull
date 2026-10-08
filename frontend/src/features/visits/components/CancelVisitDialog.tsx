import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { ReasonDialog } from "@/components/ReasonDialog";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

import { useCancelVisit, useVisitOptions } from "../api";

export interface CancelVisitDialogProps {
  /** The visit to cancel; null closes the dialog. */
  visit: { id: number; number: string } | null;
  onOpenChange: (open: boolean) => void;
}

/**
 * Visit cancellation with a reason (FEATURES 2.7, invariant 4). Paid lines are credited by the
 * server and the money becomes refundable patient credit; the dialog only collects the reason.
 */
export function CancelVisitDialog({ visit, onOpenChange }: CancelVisitDialogProps) {
  const { t } = useTranslation("visits");
  const language = useLanguage();
  const options = useVisitOptions();
  const cancel = useCancelVisit();
  const reasons = (options.data?.cancel_reasons ?? []).map((r) => ({
    code: r.code,
    label: pickName({ ar: r.label_ar, en: r.label_en }, language),
  }));
  return (
    <ReasonDialog
      open={visit !== null}
      onOpenChange={onOpenChange}
      title={t("cancel.title")}
      description={t("cancel.description")}
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
