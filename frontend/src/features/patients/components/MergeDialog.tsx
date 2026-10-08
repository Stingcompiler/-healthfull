import { ArrowDown } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { AlertCard } from "@/components/AlertCard";
import { ReasonDialog } from "@/components/ReasonDialog";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

import { useMergePatient, useMergeReasons } from "../api";
import { patientName } from "../lib";
import type { PatientFile, PatientListItem } from "../types";
import { PatientPicker } from "./PatientPicker";

export interface MergeDialogProps {
  /** The surviving file (the one being viewed). */
  target: PatientFile;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Merge a duplicate file into this one (FEATURES 1.4, supervisor permission): pick the duplicate,
 * then give the reason. Nothing is deleted; the duplicate stays as an inactive file pointing here.
 */
export function MergeDialog(props: MergeDialogProps) {
  // Mounted only while open, so each merge starts with no duplicate picked.
  return props.open ? <MergeFlow {...props} /> : null;
}

function MergeFlow({ target, open, onOpenChange }: MergeDialogProps) {
  const { t } = useTranslation(["patients", "common"]);
  const language = useLanguage();
  const merge = useMergePatient(target.id);
  const [duplicate, setDuplicate] = useState<PatientListItem | null>(null);
  const [reasonOpen, setReasonOpen] = useState(false);

  const mergeReasons = useMergeReasons();
  const reasons = (mergeReasons.data ?? []).map((r) => ({
    code: r.code,
    label: pickName({ ar: r.label_ar, en: r.label_en }, language),
  }));

  return (
    <>
      <Dialog open={open && !reasonOpen} onOpenChange={onOpenChange}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>{t("merge.title")}</DialogTitle>
            <DialogDescription>{t("merge.description")}</DialogDescription>
          </DialogHeader>
          <PatientPicker
            value={duplicate}
            onChange={setDuplicate}
            excludeIds={[target.id]}
            label={t("merge.pickLabel")}
            autoFocus
          />
          <AlertCard variant="info" title={t("merge.keepsTitle", { name: patientName(target, language) })}>
            {t("merge.keepsDescription")}
          </AlertCard>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                onOpenChange(false);
              }}
            >
              {t("common:actions.cancel")}
            </Button>
            <Button
              type="button"
              disabled={!duplicate}
              onClick={() => {
                setReasonOpen(true);
              }}
            >
              {t("common:actions.continue")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <ReasonDialog
        open={open && reasonOpen}
        onOpenChange={(next) => {
          if (!next) onOpenChange(false);
        }}
        title={t("merge.confirmTitle")}
        description={t("merge.confirmDescription")}
        reasons={reasons}
        confirmLabel={t("merge.confirm")}
        destructive
        onSubmit={async ({ code, note }) => {
          if (!duplicate) return;
          await merge.mutateAsync({
            duplicate_id: duplicate.id,
            reason_code: code,
            note,
          });
          toast.success(t("merge.done", { fileNo: duplicate.file_no }));
        }}
      >
        {duplicate ? (
          <div className="grid gap-1 rounded-control border border-border p-3 text-sm" data-testid="merge-summary">
            <p>
              <span className="text-muted">{t("merge.from")} </span>
              <span className="font-semibold break-words">{patientName(duplicate, language)}</span>{" "}
              <bdi className="tabular text-muted">{duplicate.file_no}</bdi>
            </p>
            <ArrowDown className="size-4 text-muted" aria-hidden="true" />
            <p>
              <span className="text-muted">{t("merge.into")} </span>
              <span className="font-semibold break-words">{patientName(target, language)}</span>{" "}
              <bdi className="tabular text-muted">{target.file_no}</bdi>
            </p>
          </div>
        ) : null}
      </ReasonDialog>
    </>
  );
}
