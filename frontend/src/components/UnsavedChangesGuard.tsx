import { useBlocker } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { ConfirmDialog } from "@/components/ConfirmDialog";

export interface UnsavedChangesGuardProps {
  /** True while the page holds edits that are not saved yet. */
  when: boolean;
}

/**
 * Asks before leaving a page with unsaved edits: in-app navigation (links, the section picker,
 * the bottom bar) opens a confirmation, and closing or reloading the tab gets the browser's
 * own prompt. Navigation that stays on the same page (search or filter changes) is not held.
 */
export function UnsavedChangesGuard({ when }: UnsavedChangesGuardProps) {
  const { t } = useTranslation("common");
  const blocker = useBlocker({
    shouldBlockFn: ({ current, next }) => when && current.pathname !== next.pathname,
    enableBeforeUnload: () => when,
    withResolver: true,
  });
  return (
    <ConfirmDialog
      open={blocker.status === "blocked"}
      onOpenChange={(open) => {
        if (!open) blocker.reset?.();
      }}
      title={t("unsaved.title")}
      description={t("unsaved.description")}
      confirmLabel={t("unsaved.leave")}
      cancelLabel={t("unsaved.stay")}
      destructive
      onConfirm={() => {
        blocker.proceed?.();
      }}
    />
  );
}
