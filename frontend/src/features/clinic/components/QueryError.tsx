import { RotateCcw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { Button } from "@/components/ui/button";
import { useTranslateError } from "@/lib/api/translate-error";

export interface QueryErrorProps {
  title: string;
  error: unknown;
  onRetry: () => void;
  retrying?: boolean;
  className?: string;
}

/** A failed request shown as such (never as an empty list): the translated error and a retry. */
export function QueryError({ title, error, onRetry, retrying = false, className }: QueryErrorProps) {
  const { t } = useTranslation();
  const translateError = useTranslateError();
  return (
    <AlertCard
      variant="danger"
      live
      title={title}
      className={className}
      action={
        <Button variant="outline" size="sm" loading={retrying} onClick={onRetry}>
          <RotateCcw aria-hidden="true" />
          {t("actions.retry")}
        </Button>
      }
    >
      {translateError(error)}
    </AlertCard>
  );
}
