import { useRouter, type ErrorComponentProps } from "@tanstack/react-router";
import { RefreshCw, ServerCrash } from "lucide-react";
import { useTranslation } from "react-i18next";

import { EmptyState } from "@/components/EmptyState";
import { Button } from "@/components/ui/button";
import { useTranslateError } from "@/lib/api/translate-error";

export function RouteErrorPage({ error, reset }: ErrorComponentProps) {
  const { t } = useTranslation();
  const router = useRouter();
  const translateError = useTranslateError();
  return (
    <div className="flex min-h-[60dvh] items-center justify-center bg-bg p-4">
      <EmptyState
        className="w-full max-w-lg"
        icon={<ServerCrash />}
        title={t("errorBoundary.title")}
        description={translateError(error)}
        action={
          <Button
            onClick={() => {
              reset();
              void router.invalidate();
            }}
          >
            <RefreshCw />
            {t("actions.retry")}
          </Button>
        }
        secondaryAction={
          <Button
            variant="outline"
            onClick={() => {
              window.location.reload();
            }}
          >
            {t("actions.reload")}
          </Button>
        }
      />
    </div>
  );
}
