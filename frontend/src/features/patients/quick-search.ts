import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { QuickSearchSource } from "@/components/AppShell";
import { usePermission } from "@/lib/auth/hooks";

import { PatientQuickResults } from "./components/PatientQuickResults";

/**
 * Patient files in the global quick search (Ctrl/⌘+K, FEATURES 0.9): name in Arabic or
 * English (spelling variants folded by the server), phone or file number. Only for holders of
 * `patients.view`; the server checks it again.
 */
export function usePatientQuickSearch(): QuickSearchSource | undefined {
  const { t } = useTranslation("patients");
  const canView = usePermission("patients.view");
  return useMemo(
    () =>
      canView
        ? {
            Results: PatientQuickResults,
            triggerLabel: t("quickSearch.trigger"),
            placeholder: t("quickSearch.placeholder"),
          }
        : undefined,
    [canView, t],
  );
}
