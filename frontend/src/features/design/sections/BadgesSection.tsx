import { useTranslation } from "react-i18next";

import { SERVICE_LINE_STATES, VERIFICATION_STATES } from "@/components/status";
import { StatusBadge } from "@/components/StatusBadge";
import { Badge } from "@/components/ui/badge";

import { Demo, Section } from "../Section";

export function BadgesSection() {
  const { t } = useTranslation("design");
  return (
    <Section id="badges" title={t("sections.badges")} description={t("descriptions.badges")}>
      <Demo label={t("badges.serviceStates")} className="flex flex-wrap gap-2">
        {SERVICE_LINE_STATES.map((s) => (
          <StatusBadge key={s} status={s} />
        ))}
      </Demo>
      <Demo label={t("badges.paymentStates")} className="flex flex-wrap gap-2">
        {VERIFICATION_STATES.map((s) => (
          <StatusBadge key={s} status={s} />
        ))}
      </Demo>
      <Demo label={t("badges.compact")} className="flex flex-wrap gap-1.5">
        {[...SERVICE_LINE_STATES, ...VERIFICATION_STATES].map((s) => (
          <StatusBadge key={s} status={s} size="sm" />
        ))}
      </Demo>
      <Demo label={t("badges.general")} className="flex flex-wrap gap-2">
        <Badge>{t("badges.brand")}</Badge>
        <Badge variant="soft">{t("badges.soft")}</Badge>
        <Badge variant="neutral">{t("badges.neutral")}</Badge>
        <Badge variant="outline">{t("badges.outline")}</Badge>
        <Badge variant="success">{t("badges.success")}</Badge>
        <Badge variant="warning">{t("badges.warning")}</Badge>
        <Badge variant="danger">{t("badges.danger")}</Badge>
        <Badge variant="info">{t("badges.info")}</Badge>
      </Demo>
    </Section>
  );
}
