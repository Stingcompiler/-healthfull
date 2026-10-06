import { Plus, Printer, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { ArrowNext } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

import { Demo, Section } from "../Section";

export function ButtonsSection() {
  const { t } = useTranslation("design");
  return (
    <Section id="buttons" title={t("sections.buttons")} description={t("descriptions.buttons")}>
      <Demo label={t("buttons.variants")} className="flex flex-wrap items-center gap-2">
        <Button>{t("buttons.primary")}</Button>
        <Button variant="secondary">{t("buttons.secondary")}</Button>
        <Button variant="outline">{t("buttons.outline")}</Button>
        <Button variant="ghost">{t("buttons.ghost")}</Button>
        <Button variant="soft">{t("buttons.soft")}</Button>
        <Button variant="destructive">
          <Trash2 />
          {t("buttons.destructive")}
        </Button>
        <Button variant="destructive-soft">{t("buttons.destructiveSoft")}</Button>
        <Button variant="link">{t("buttons.link")}</Button>
      </Demo>
      <Demo label={t("buttons.sizes")} className="flex flex-wrap items-center gap-2">
        <Button size="sm">{t("buttons.small")}</Button>
        <Button>{t("buttons.medium")}</Button>
        <Button size="lg">
          {t("buttons.large")}
          <ArrowNext />
        </Button>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button size="icon" variant="outline" aria-label={t("buttons.iconOnly")}>
              <Plus />
            </Button>
          </TooltipTrigger>
          <TooltipContent>{t("buttons.iconOnly")}</TooltipContent>
        </Tooltip>
        <Button size="icon-sm" variant="ghost" aria-label={t("buttons.iconOnly")}>
          <Plus />
        </Button>
      </Demo>
      <Demo label={t("buttons.states")} className="flex flex-wrap items-center gap-2">
        <Button variant="outline">
          <Printer />
          {t("buttons.withIcon")}
        </Button>
        <Button loading>{t("buttons.loading")}</Button>
        <Button disabled>{t("buttons.disabled")}</Button>
        <Button variant="outline" disabled>
          {t("buttons.disabled")}
        </Button>
      </Demo>
    </Section>
  );
}
