import { useCallback, useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { ConfirmDialog } from "@/components/ConfirmDialog";

/**
 * Asks before an in-page switch (a tab, a template picker) throws away unsaved edits.
 * `UnsavedChangesGuard` covers leaving the page; this covers what stays on it.
 *
 *   const discard = useDiscardConfirm();
 *   discard.ask(dirty, () => setTab(next));
 *   return <>{...}{discard.dialog}</>;
 */
export function useDiscardConfirm(): { ask: (dirty: boolean, action: () => void) => void; dialog: ReactNode } {
  const { t } = useTranslation("common");
  const [pending, setPending] = useState<(() => void) | null>(null);
  const ask = useCallback((dirty: boolean, action: () => void) => {
    if (dirty) setPending(() => action);
    else action();
  }, []);
  const dialog = (
    <ConfirmDialog
      open={pending !== null}
      onOpenChange={(open) => {
        if (!open) setPending(null);
      }}
      title={t("unsaved.discardTitle")}
      description={t("unsaved.discardDescription")}
      confirmLabel={t("unsaved.discard")}
      cancelLabel={t("unsaved.stay")}
      destructive
      onConfirm={() => {
        const action = pending;
        setPending(null);
        action?.();
      }}
    />
  );
  return { ask, dialog };
}

/** Reports a form's dirty flag to its parent, and "clean" when the form goes away. */
export function useReportDirty(dirty: boolean, onDirtyChange?: (dirty: boolean) => void): void {
  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);
  useEffect(
    () => () => {
      onDirtyChange?.(false);
    },
    [onDirtyChange],
  );
}
