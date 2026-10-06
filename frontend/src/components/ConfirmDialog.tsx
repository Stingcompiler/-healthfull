import { TriangleAlert } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { toApiError } from "@/lib/api/errors";
import { useTranslateError } from "@/lib/api/translate-error";

export interface ConfirmDialogProps {
  /** Element that opens the dialog (uncontrolled use). */
  trigger?: ReactNode;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  title?: ReactNode;
  description?: ReactNode;
  confirmLabel?: ReactNode;
  cancelLabel?: ReactNode;
  destructive?: boolean;
  /** May return a promise; the dialog shows progress and stays open on error. */
  onConfirm: () => void | Promise<void>;
  children?: ReactNode;
}

export function ConfirmDialog({
  trigger,
  open: openProp,
  onOpenChange,
  title,
  description,
  confirmLabel,
  cancelLabel,
  destructive = false,
  onConfirm,
  children,
}: ConfirmDialogProps) {
  const { t } = useTranslation(["common", "errors"]);
  const translateError = useTranslateError();
  const [internalOpen, setInternalOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const open = openProp ?? internalOpen;

  const setOpen = (next: boolean) => {
    if (pending) return;
    if (!next) setError(null);
    setInternalOpen(next);
    onOpenChange?.(next);
  };

  const confirm = async () => {
    setPending(true);
    setError(null);
    try {
      await onConfirm();
      setPending(false);
      setInternalOpen(false);
      onOpenChange?.(false);
    } catch (e) {
      setPending(false);
      setError(translateError(toApiError(e)));
    }
  };

  return (
    <AlertDialog open={open} onOpenChange={setOpen}>
      {trigger ? <AlertDialogTrigger asChild>{trigger}</AlertDialogTrigger> : null}
      <AlertDialogContent>
        <AlertDialogHeader>
          <div className="flex items-start gap-3">
            {destructive ? (
              <div className="flex size-10 shrink-0 items-center justify-center rounded-full bg-danger-bg text-danger-fg">
                <TriangleAlert className="size-5" aria-hidden="true" />
              </div>
            ) : null}
            <div className="grid gap-1.5">
              <AlertDialogTitle>{title ?? t("confirm.title")}</AlertDialogTitle>
              <AlertDialogDescription>{description ?? t("confirm.description")}</AlertDialogDescription>
            </div>
          </div>
        </AlertDialogHeader>
        {children}
        {error ? (
          <AlertCard variant="danger" title={t("errors:title")} live>
            {error}
          </AlertCard>
        ) : null}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending}>{cancelLabel ?? t("actions.cancel")}</AlertDialogCancel>
          <Button variant={destructive ? "destructive" : "default"} loading={pending} onClick={() => void confirm()}>
            {confirmLabel ?? t("actions.confirm")}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
