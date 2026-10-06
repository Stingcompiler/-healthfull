import { useTranslation } from "react-i18next";

import { MoneyText } from "@/components/MoneyText";
import { Card } from "@/components/ui/card";

import { Demo, Section } from "../Section";

export function TypographySection() {
  const { t } = useTranslation("design");
  return (
    <Section id="typography" title={t("sections.typography")} description={t("descriptions.typography")}>
      <Card className="gap-5">
        <p className="text-3xl leading-tight font-bold tracking-tight text-fg md:text-4xl">{t("typography.display")}</p>
        <p className="text-xl font-bold text-fg md:text-2xl">{t("typography.heading")}</p>
        <p className="text-base font-semibold text-fg">{t("typography.subheading")}</p>
        <p className="max-w-prose text-sm leading-7 text-fg md:text-base">{t("typography.body")}</p>
        <p className="text-sm text-muted">{t("typography.muted")}</p>
      </Card>
      <div className="grid gap-4 md:grid-cols-2">
        <Demo label={t("typography.numbers")}>
          <Card className="gap-2 tabular">
            <MoneyText value="1234567.50" className="text-lg" />
            <MoneyText value="98000.00" className="text-lg" />
            <MoneyText value="15.25" className="text-lg" />
          </Card>
        </Demo>
        <Demo label={t("typography.mixed")}>
          <Card>
            <p className="text-sm leading-7 text-fg">{t("typography.mixedSample")}</p>
          </Card>
        </Demo>
      </div>
    </Section>
  );
}
