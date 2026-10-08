import { Link } from "@tanstack/react-router";
import { TriangleAlert } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";
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

import { patientName } from "../lib";
import type { DuplicateCandidate } from "../types";

export interface DuplicateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  candidates: readonly DuplicateCandidate[];
  /** Register a new file anyway (the receptionist confirmed it is another person). */
  onConfirm: () => void;
  pending?: boolean;
}

/** Duplicate warning (FEATURES 1.3): similar files, why they match, and the way forward. */
export function DuplicateDialog({ open, onOpenChange, candidates, onConfirm, pending = false }: DuplicateDialogProps) {
  const { t } = useTranslation("patients");
  const language = useLanguage();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <TriangleAlert className="size-5 text-warning" aria-hidden="true" />
            {t("duplicates.title")}
          </DialogTitle>
          <DialogDescription>{t("duplicates.description")}</DialogDescription>
        </DialogHeader>
        <ul className="grid gap-2" aria-label={t("duplicates.listLabel")}>
          {candidates.map((c) => (
            <li
              key={c.patient.id}
              className="flex min-w-0 flex-wrap items-center gap-3 rounded-control border border-border p-3"
            >
              <div className="min-w-0 flex-1">
                <p className="font-semibold break-words text-fg">{patientName(c.patient, language)}</p>
                <p className="text-xs text-muted">
                  <bdi className="tabular">{c.patient.file_no}</bdi>
                  {c.patient.phone ? (
                    <>
                      {" · "}
                      <bdi className="tabular">{c.patient.phone}</bdi>
                    </>
                  ) : null}
                </p>
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {c.reasons.map((r) => (
                    <Badge key={r} variant="warning">
                      {t(`duplicates.reason.${r}`)}
                    </Badge>
                  ))}
                </div>
              </div>
              <Button asChild variant="outline" size="sm">
                <Link to="/patients/$patientId" params={{ patientId: String(c.patient.id) }}>
                  {t("duplicates.openFile")}
                </Link>
              </Button>
            </li>
          ))}
        </ul>
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              onOpenChange(false);
            }}
          >
            {t("duplicates.back")}
          </Button>
          <Button type="button" variant="destructive-soft" loading={pending} onClick={onConfirm}>
            {t("duplicates.registerAnyway")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
