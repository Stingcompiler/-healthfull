import { ArrowLeftRight, LogOut } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { AlertCard } from "@/components/AlertCard";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useTranslateError } from "@/lib/api/translate-error";
import { useLanguage } from "@/lib/i18n-hooks";

import { useDischarge, useTransfer } from "../api";
import { nameOf, patientName } from "../lib";
import type { Bed, Occupant } from "../types";

export interface OccupiedBed {
  bed: Bed;
  occupant: Occupant;
}

/** Move an inpatient to a free bed (FEATURES 10.5). */
export function TransferDialog({
  target,
  freeBeds,
  onOpenChange,
}: {
  target: OccupiedBed | null;
  freeBeds: readonly Bed[];
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation("nursing");
  const { t: tc } = useTranslation();
  const language = useLanguage();
  const translateError = useTranslateError();
  const transfer = useTransfer();
  const [bed, setBed] = useState("");
  const [error, setError] = useState<string | null>(null);
  const close = () => {
    setBed("");
    setError(null);
    onOpenChange(false);
  };
  const name = target ? patientName(target.occupant.patient, language) : "";

  return (
    <Dialog
      open={target !== null}
      onOpenChange={(open) => {
        if (!open) close();
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ArrowLeftRight className="size-5 text-muted" aria-hidden="true" />
            {t("transfer.title")}
          </DialogTitle>
          {target ? (
            <DialogDescription>{t("transfer.description", { name, bed: target.bed.code })}</DialogDescription>
          ) : null}
        </DialogHeader>
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (!target || !bed) return;
            setError(null);
            transfer.mutate(
              { admissionId: target.occupant.admission_id, bedId: Number(bed) },
              {
                onSuccess: (adm) => {
                  toast.success(t("transfer.savedToast", { name, bed: adm.bed?.code ?? "" }));
                  close();
                },
                onError: (err) => {
                  setError(translateError(err));
                },
              },
            );
          }}
        >
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="transfer-bed">{t("transfer.bed")}</Label>
            <Select value={bed} onValueChange={setBed} disabled={freeBeds.length === 0}>
              <SelectTrigger id="transfer-bed" className="h-12" data-testid="transfer-bed">
                <SelectValue placeholder={t("admit.choose")} />
              </SelectTrigger>
              <SelectContent>
                {freeBeds.map((b) => (
                  <SelectItem key={b.id} value={String(b.id)}>
                    {b.code} · {nameOf(b, language)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {freeBeds.length === 0 ? <p className="text-xs text-warning-fg">{t("admit.noFreeBeds")}</p> : null}
          </div>
          {error ? (
            <AlertCard variant="danger" live title={t("transfer.error")}>
              {error}
            </AlertCard>
          ) : null}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={close}>
              {tc("actions.cancel")}
            </Button>
            <Button type="submit" loading={transfer.isPending} disabled={!bed} data-testid="transfer-confirm">
              {t("transfer.confirm")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Discharge: the remaining nights are charged, the bed is freed, the visit closes. */
export function DischargeDialog({
  target,
  onOpenChange,
}: {
  target: OccupiedBed | null;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation("nursing");
  const { t: tc } = useTranslation();
  const language = useLanguage();
  const translateError = useTranslateError();
  const discharge = useDischarge();
  const [summary, setSummary] = useState("");
  const [error, setError] = useState<string | null>(null);
  const close = () => {
    setSummary("");
    setError(null);
    onOpenChange(false);
  };
  const name = target ? patientName(target.occupant.patient, language) : "";

  return (
    <Dialog
      open={target !== null}
      onOpenChange={(open) => {
        if (!open) close();
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <LogOut className="size-5 text-muted rtl:-scale-x-100" aria-hidden="true" />
            {t("discharge.title")}
          </DialogTitle>
          {target ? (
            <DialogDescription>{t("discharge.description", { name, bed: target.bed.code })}</DialogDescription>
          ) : null}
        </DialogHeader>
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (!target) return;
            setError(null);
            discharge.mutate(
              { admissionId: target.occupant.admission_id, summary: summary.trim() },
              {
                onSuccess: () => {
                  toast.success(t("discharge.savedToast", { name }));
                  close();
                },
                onError: (err) => {
                  setError(translateError(err));
                },
              },
            );
          }}
        >
          {target ? (
            <AlertCard variant="info" title={t("discharge.nights", { count: target.occupant.nights_at_discharge })} />
          ) : null}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="discharge-summary">{t("discharge.summary")}</Label>
            <Textarea
              id="discharge-summary"
              rows={3}
              maxLength={2000}
              value={summary}
              placeholder={t("discharge.summaryPlaceholder")}
              onChange={(e) => {
                setSummary(e.target.value);
              }}
            />
          </div>
          {error ? (
            <AlertCard variant="danger" live title={t("discharge.error")}>
              {error}
            </AlertCard>
          ) : null}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={close}>
              {tc("actions.cancel")}
            </Button>
            <Button type="submit" loading={discharge.isPending} data-testid="discharge-confirm">
              {t("discharge.confirm")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
