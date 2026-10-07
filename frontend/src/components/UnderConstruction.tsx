import { Construction } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Link } from "@tanstack/react-router";

export interface UnderConstructionProps {
  title: ReactNode;
  description: ReactNode;
  icon: ReactNode;
}

/** Placeholder page for a pre-registered module that is not built yet. */
export function UnderConstruction({ title, description, icon }: UnderConstructionProps) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title={title} description={description} icon={icon} />
      <EmptyState
        icon={<Construction />}
        title={t("underConstruction.title")}
        description={t("underConstruction.description")}
        action={
          <Button asChild variant="outline">
            <Link to="/">{t("underConstruction.action")}</Link>
          </Button>
        }
      />
    </div>
  );
}
