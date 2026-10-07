import { useState } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { EmptyState } from "@/components/EmptyState";
import { Button } from "@/components/ui/button";
import { FileSpreadsheet, ListOrdered, UserPlus } from "lucide-react";

import { Demo, Section } from "../Section";

export function AlertsSection() {
  const { t } = useTranslation("design");
  const [dismissed, setDismissed] = useState(false);
  return (
    <Section id="alerts" title={t("sections.alerts")} description={t("descriptions.alerts")}>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <AlertCard variant="info" title={t("alerts.infoTitle")}>
          {t("alerts.infoBody")}
        </AlertCard>
        <AlertCard variant="success" title={t("alerts.successTitle")}>
          {t("alerts.successBody")}
        </AlertCard>
        <AlertCard
          variant="warning"
          title={t("alerts.warningTitle")}
          action={
            <Button size="sm" variant="outline">
              {t("alerts.action")}
            </Button>
          }
        >
          {t("alerts.warningBody")}
        </AlertCard>
        {dismissed ? (
          <div className="flex items-center justify-center rounded-card border border-dashed border-border p-4 text-sm text-muted">
            <Button
              variant="link"
              onClick={() => {
                setDismissed(false);
              }}
            >
              {t("alerts.restore")}
            </Button>
          </div>
        ) : (
          <AlertCard
            variant="danger"
            title={t("alerts.dangerTitle")}
            onDismiss={() => {
              setDismissed(true);
            }}
          >
            {t("alerts.dangerBody")}
          </AlertCard>
        )}
      </div>
    </Section>
  );
}

export function EmptySection() {
  const { t } = useTranslation("design");
  return (
    <Section id="empty" title={t("sections.empty")} description={t("descriptions.empty")}>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[2fr_1fr]">
        <Demo label={t("empty.noPatientsTitle")}>
          <EmptyState
            icon={<UserPlus />}
            title={t("empty.noPatientsTitle")}
            description={t("empty.noPatientsBody")}
            action={<Button>{t("empty.noPatientsAction")}</Button>}
            secondaryAction={
              <Button variant="outline">
                <FileSpreadsheet />
                {t("empty.importAction")}
              </Button>
            }
          />
        </Demo>
        <Demo label={t("empty.noQueueTitle")}>
          <EmptyState
            size="compact"
            icon={<ListOrdered />}
            title={t("empty.noQueueTitle")}
            description={t("empty.noQueueBody")}
          />
        </Demo>
      </div>
    </Section>
  );
}
