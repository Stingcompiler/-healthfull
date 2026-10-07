import { Moon, Sun, Sunset, type LucideIcon } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { isTheme, THEMES, type Theme } from "@/lib/preferences";
import { usePreferences } from "@/lib/use-preferences";
import { cn } from "@/lib/utils";

const THEME_ICONS: Record<Theme, LucideIcon> = { light: Sun, dark: Moon, warm: Sunset };

/**
 * A swatch of another theme's brand color. tokens.css scopes every theme to
 * `[data-theme=...]`, so setting the attribute on the swatch itself makes
 * `bg-primary` resolve to that theme's value. No raw colors needed.
 */
export function ThemeSwatch({ theme, className }: { theme: Theme; className?: string }) {
  return (
    <span
      data-theme={theme}
      aria-hidden="true"
      className={cn("inline-flex size-3.5 overflow-hidden rounded-full ring-1 ring-border", className)}
    >
      <span className="w-1/2 bg-primary" />
      <span className="w-1/2 bg-bg" />
    </span>
  );
}

export interface ThemeSwitcherProps {
  /** "menu": icon button with dropdown (top bar). "segmented": three inline buttons. */
  variant?: "menu" | "segmented";
  className?: string;
}

export function ThemeSwitcher({ variant = "menu", className }: ThemeSwitcherProps) {
  const { t } = useTranslation();
  const { theme, setTheme } = usePreferences();
  const CurrentIcon = THEME_ICONS[theme];

  if (variant === "segmented") {
    return (
      <div
        role="radiogroup"
        aria-label={t("theme.label")}
        className={cn("inline-flex items-center gap-1 rounded-control border border-border bg-surface p-1", className)}
      >
        {THEMES.map((value) => {
          const Icon = THEME_ICONS[value];
          const selected = value === theme;
          return (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={selected}
              onClick={() => {
                setTheme(value);
              }}
              className={cn(
                "inline-flex h-11 items-center gap-1.5 rounded-[6px] px-2.5 text-xs font-medium text-muted transition-colors md:h-8",
                "focus-ring hover:bg-accent hover:text-fg",
                selected && "bg-primary-soft text-primary-strong hover:bg-primary-soft hover:text-primary-strong",
              )}
            >
              <Icon className="size-4" aria-hidden="true" />
              {t(`theme.${value}`)}
            </button>
          );
        })}
      </div>
    );
  }

  return (
    <DropdownMenu>
      <Tooltip>
        <TooltipTrigger asChild>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" className={className} aria-label={t("theme.change")}>
              <CurrentIcon />
            </Button>
          </DropdownMenuTrigger>
        </TooltipTrigger>
        <TooltipContent>{t("theme.change")}</TooltipContent>
      </Tooltip>
      <DropdownMenuContent align="end" className="w-44">
        <DropdownMenuLabel>{t("theme.label")}</DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={theme}
          onValueChange={(value) => {
            if (isTheme(value)) setTheme(value);
          }}
        >
          {THEMES.map((value) => {
            const Icon = THEME_ICONS[value];
            return (
              <DropdownMenuRadioItem key={value} value={value}>
                <Icon aria-hidden="true" />
                <span className="flex-1">{t(`theme.${value}`)}</span>
                <ThemeSwatch theme={value} />
              </DropdownMenuRadioItem>
            );
          })}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
