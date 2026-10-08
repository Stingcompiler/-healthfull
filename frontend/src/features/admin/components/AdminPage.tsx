import { ShieldOff } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";
import { useCurrentUser } from "@/lib/auth/hooks";
import { hasPermission } from "@/lib/auth/permissions";

import { adminSection, type AdminSectionId } from "../sections";

export interface AdminPageProps {
  section: AdminSectionId;
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  /** Document title when the heading is not plain text. */
  documentTitle?: string;
  children: ReactNode;
}

/**
 * A section page: its header, or a "no access" state for users without the
 * section's permission (the server refuses them anyway; this only explains it).
 */
export function AdminPage({ section, title, description, actions, documentTitle, children }: AdminPageProps) {
  const { t } = useTranslation("admin");
  const me = useCurrentUser();
  const def = adminSection(section);
  const Icon = def.icon;
  const allowed = hasPermission(me, def.permission);
  return (
    <div className="flex min-w-0 flex-col gap-5">
      <PageHeader
        title={title}
        description={description}
        icon={<Icon />}
        actions={allowed ? actions : undefined}
        documentTitle={documentTitle}
      />
      {allowed ? (
        children
      ) : (
        <EmptyState icon={<ShieldOff />} title={t("noAccess.title")} description={t("noAccess.description")} />
      )}
    </div>
  );
}

/** Loading skeleton or error card for a query; renders children once data is there. */
export function QueryState({
  loading,
  error,
  onRetry,
  rows = 4,
  children,
}: {
  loading: boolean;
  error: unknown;
  onRetry?: () => void;
  rows?: number;
  children: ReactNode;
}) {
  const { t } = useTranslation(["common", "errors"]);
  const translateError = useTranslateError();
  if (error) {
    return (
      <AlertCard
        variant="danger"
        title={t("errors:title")}
        action={
          onRetry ? (
            <Button variant="outline" size="sm" onClick={onRetry}>
              {t("actions.retry")}
            </Button>
          ) : undefined
        }
      >
        {translateError(error)}
      </AlertCard>
    );
  }
  if (loading) {
    return (
      <div className="grid gap-3" aria-busy="true" aria-label={t("loading")}>
        {Array.from({ length: rows }, (_, i) => (
          <Skeleton key={i} className="h-12 w-full" />
        ))}
      </div>
    );
  }
  return <>{children}</>;
}
