import { Printer } from "lucide-react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";

import { DateText } from "@/components/DateText";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { patientName } from "@/features/patients/lib";
import { formatNumber } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

import { useTokenSlip } from "../api";
import type { TokenSlip } from "../types";

/**
 * Thermal 80 mm page: only the slip prints. System colors with a light color scheme keep the
 * text black on paper whatever the screen theme (no raw colors).
 */
const PRINT_CSS = `
@media print {
  @page { size: 80mm auto; margin: 0; }
  body > :not(#token-print-root) { display: none !important; }
  #token-print-root { display: block !important; color-scheme: light; color: CanvasText; background: Canvas; }
}
`;

export interface TokenSlipDialogProps {
  entryId: number | null;
  onOpenChange: (open: boolean) => void;
}

/** Queue token slip (FEATURES 2.6): preview and print on the 80 mm receipt printer. */
export function TokenSlipDialog({ entryId, onOpenChange }: TokenSlipDialogProps) {
  const { t } = useTranslation(["visits", "common"]);
  const slip = useTokenSlip(entryId);
  return (
    <Dialog open={entryId !== null} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>{t("token.title")}</DialogTitle>
          <DialogDescription>{t("token.description")}</DialogDescription>
        </DialogHeader>
        {slip.data ? (
          <div className="rounded-control border border-dashed border-border-strong p-4">
            <SlipBody slip={slip.data} />
          </div>
        ) : (
          <Skeleton className="h-56" />
        )}
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              onOpenChange(false);
            }}
          >
            {t("common:actions.close")}
          </Button>
          <Button
            type="button"
            disabled={!slip.data}
            onClick={() => {
              window.print();
            }}
          >
            <Printer aria-hidden="true" />
            {t("token.print")}
          </Button>
        </DialogFooter>
        {slip.data
          ? createPortal(
              <div id="token-print-root" className="hidden" aria-hidden="true">
                <style>{PRINT_CSS}</style>
                <div className="w-[72mm] p-[4mm]">
                  <SlipBody slip={slip.data} />
                </div>
              </div>,
              document.body,
            )
          : null}
      </DialogContent>
    </Dialog>
  );
}

function SlipBody({ slip }: { slip: TokenSlip }) {
  const { t } = useTranslation("visits");
  const language = useLanguage();
  const { entry, center } = slip;
  const centerName = pickName({ ar: center.name_ar, en: center.name_en }, language);
  return (
    <div className="flex flex-col items-center gap-1 text-center" data-testid="token-slip">
      {centerName ? <p className="text-sm font-semibold">{centerName}</p> : null}
      <p className="text-sm">{pickName({ ar: entry.department.name_ar, en: entry.department.name_en }, language)}</p>
      <p className="text-xs">{t("token.number")}</p>
      <p className="tabular text-6xl leading-none font-bold" data-testid="token-number">
        {formatNumber(entry.token_no, language)}
      </p>
      {entry.doctor ? (
        <p className="text-sm">{pickName({ ar: entry.doctor.name_ar, en: entry.doctor.name_en }, language)}</p>
      ) : null}
      <p className="mt-1 text-sm font-medium break-words">{patientName(entry.patient, language)}</p>
      <p className="text-xs">
        <bdi className="tabular">{entry.patient.file_no}</bdi>
        {" · "}
        <bdi className="tabular">{entry.visit_number}</bdi>
      </p>
      <p className="text-xs">{t("token.ahead", { count: slip.ahead })}</p>
      <p className="text-xs">
        <DateText value={entry.created_at} format="datetime" />
      </p>
    </div>
  );
}
