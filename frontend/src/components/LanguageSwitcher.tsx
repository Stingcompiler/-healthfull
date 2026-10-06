import { Languages } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { Language } from "@/lib/preferences";
import { usePreferences } from "@/lib/use-preferences";
import { cn } from "@/lib/utils";

export interface LanguageSwitcherProps {
  /** "button": label of the other language. "icon": compact icon button. */
  variant?: "button" | "icon";
  className?: string;
}

/**
 * Toggles Arabic/English. The label is always written in the target
 * language ("English" / "العربية") so a user who cannot read the current
 * one still finds it.
 */
export function LanguageSwitcher({ variant = "button", className }: LanguageSwitcherProps) {
  const { t } = useTranslation();
  const { language, setLanguage } = usePreferences();
  const next: Language = language === "ar" ? "en" : "ar";
  const nextName = t(`language.${next}`);
  const label = t("language.switchTo", { language: nextName });

  if (variant === "icon") {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            className={className}
            aria-label={label}
            onClick={() => {
              setLanguage(next);
            }}
          >
            <Languages />
          </Button>
        </TooltipTrigger>
        <TooltipContent>{label}</TooltipContent>
      </Tooltip>
    );
  }

  return (
    <Button
      variant="ghost"
      className={cn("gap-1.5 px-2.5", className)}
      aria-label={label}
      onClick={() => {
        setLanguage(next);
      }}
    >
      <Languages aria-hidden="true" />
      <span lang={next}>{nextName}</span>
    </Button>
  );
}
