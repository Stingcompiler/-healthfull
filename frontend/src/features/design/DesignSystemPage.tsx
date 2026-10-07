import { Palette } from "lucide-react";
import { useTranslation } from "react-i18next";

import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { PageHeader } from "@/components/PageHeader";
import { ThemeSwitcher } from "@/components/ThemeSwitcher";

import { AlertsSection, EmptySection } from "./sections/AlertsSection";
import { BadgesSection } from "./sections/BadgesSection";
import { ButtonsSection } from "./sections/ButtonsSection";
import { CardsSection } from "./sections/CardsSection";
import { ColorsSection } from "./sections/ColorsSection";
import { FormsSection } from "./sections/FormsSection";
import {
  AccessSection,
  ControlsSection,
  FeedbackSection,
  FormattingSection,
  ShortcutsSection,
} from "./sections/MiscSections";
import { OverlaysSection } from "./sections/OverlaysSection";
import { TableSection } from "./sections/TableSection";
import { TypographySection } from "./sections/TypographySection";

const SECTION_IDS = [
  "colors",
  "typography",
  "buttons",
  "badges",
  "cards",
  "alerts",
  "empty",
  "forms",
  "table",
  "overlays",
  "feedback",
  "controls",
  "formatting",
  "shortcuts",
  "access",
] as const;

/**
 * Living style guide (/design). Shows every shared component in every
 * variant and state; e2e takes its screenshots from here for visual review
 * across 3 themes x 2 languages x 3 viewports.
 */
export function DesignSystemPage() {
  const { t } = useTranslation("design");
  return (
    <div className="flex flex-col gap-10">
      <div className="flex flex-col gap-4">
        <PageHeader
          title={t("title")}
          description={t("subtitle")}
          icon={<Palette />}
          actions={
            <div className="flex flex-wrap items-center gap-2" role="group" aria-label={t("preview")}>
              <ThemeSwitcher variant="segmented" />
              <LanguageSwitcher className="border border-border" />
            </div>
          }
        />
        <nav aria-label={t("toc")} className="-mx-1 scrollbar-thin overflow-x-auto px-1 pb-1">
          <ul className="flex w-max gap-1.5 md:w-auto md:flex-wrap">
            {SECTION_IDS.map((id) => (
              <li key={id}>
                <a
                  href={`#${id}`}
                  className="inline-flex h-8 items-center rounded-full border border-border bg-surface px-3 text-xs font-medium whitespace-nowrap text-muted focus-ring transition-colors hover:border-primary/40 hover:text-fg"
                >
                  {t(`sections.${id}`)}
                </a>
              </li>
            ))}
          </ul>
        </nav>
      </div>

      <ColorsSection />
      <TypographySection />
      <ButtonsSection />
      <BadgesSection />
      <CardsSection />
      <AlertsSection />
      <EmptySection />
      <FormsSection />
      <TableSection />
      <OverlaysSection />
      <FeedbackSection />
      <ControlsSection />
      <FormattingSection />
      <ShortcutsSection />
      <AccessSection />
    </div>
  );
}
