import { Link } from "@tanstack/react-router";
import { Activity, Banknote, Clock3, Users } from "lucide-react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { KpiCard } from "@/components/KpiCard";
import { MoneyText } from "@/components/MoneyText";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { useCurrentUser } from "@/lib/auth/hooks";
import { formatNumber } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

/**
 * Phase 0 dashboard: the real layout with zero figures. The numbers come
 * from the reports module once billing and payments exist.
 */
export function DashboardPage() {
  const { t } = useTranslation("dashboard");
  const language = useLanguage();
  const me = useCurrentUser();
  const name = me ? pickName({ ar: me.full_name_ar, en: me.full_name_en }, language) || me.username : "";
  const zero = formatNumber(0, language);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow={<DateText value={new Date()} format="long" />}
        title={t("greeting", { name })}
        description={t("subtitle")}
      />

      <AlertCard variant="info" title={t("setupAlert.title")}>
        {t("setupAlert.description")}
      </AlertCard>

      <section aria-label={t("title")} className="grid grid-cols-2 gap-3 md:gap-4 xl:grid-cols-4">
        <KpiCard label={t("kpi.visitsToday")} value={zero} icon={<Users />} hint={t("kpi.noData")} />
        <KpiCard label={t("kpi.queueWaiting")} value={zero} icon={<Clock3 />} tone="info" hint={t("kpi.noData")} />
        <KpiCard
          label={t("kpi.collectedToday")}
          value={<MoneyText value="0.00" />}
          icon={<Banknote />}
          tone="success"
          hint={t("kpi.noData")}
        />
        <KpiCard
          label={t("kpi.pendingTransfers")}
          value={zero}
          icon={<Activity />}
          tone="warning"
          hint={t("kpi.noData")}
        />
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-base font-semibold text-fg">{t("activity.title")}</h2>
        <EmptyState
          icon={<Activity />}
          title={t("activity.emptyTitle")}
          description={t("activity.emptyDescription")}
          action={
            <Button asChild>
              <Link to="/patients">{t("activity.emptyAction")}</Link>
            </Button>
          }
        />
      </section>
    </div>
  );
}
