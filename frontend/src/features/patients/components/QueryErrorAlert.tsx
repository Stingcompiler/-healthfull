import { RotateCcw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { Button } from "@/components/ui/button";
import { useTranslateError } from "@/lib/api/translate-error";

export interface QueryErrorAlertProps {
  /** What failed to load, e.g. "The patient list could not be loaded." */
  title: string;
  error: unknown;
  onRetry: () => void;
  retrying?: boolean;
  className?: string;
}

/**
 * A failed request shown as such (never as an empty list): the translated error and a retry.
 * Used by the patients and visits screens for every query they show.
 */
export function QueryErrorAlert({ title, error, onRetry, retrying = false, className }: QueryErrorAlertProps) {
  const { t } = useTranslation("common");
  const translateError = useTranslateError();
  return (
    <AlertCard
      variant="danger"
      live
      title={title}
      className={className}
      action={
        <Button variant="outline" size="sm" loading={retrying} onClick={onRetry} data-testid="query-retry">
          <RotateCcw aria-hidden="true" />
          {t("actions.retry")}
        </Button>
      }
    >
      {translateError(error)}
    </AlertCard>
  );
}
