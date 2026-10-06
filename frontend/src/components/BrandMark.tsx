import { useTranslation } from "react-i18next";

import { cn } from "@/lib/utils";

/** The app mark: a rounded tile with a medical cross, in the theme's primary color. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "inline-flex size-9 shrink-0 items-center justify-center rounded-[10px] bg-primary text-primary-fg shadow-card",
        className,
      )}
    >
      <svg viewBox="0 0 24 24" className="size-[60%]" fill="currentColor">
        <path d="M9.5 3h5v6.5H21v5h-6.5V21h-5v-6.5H3v-5h6.5z" />
      </svg>
    </span>
  );
}

export function Brand({ collapsed = false, className }: { collapsed?: boolean; className?: string }) {
  const { t } = useTranslation();
  return (
    <span className={cn("flex min-w-0 items-center gap-2.5", className)}>
      <BrandMark />
      {collapsed ? (
        <span className="sr-only">{t("appName")}</span>
      ) : (
        <span className="min-w-0 leading-tight">
          <span className="block truncate text-sm font-bold text-fg">{t("appShortName")}</span>
          <span className="block truncate text-[11px] text-muted">{t("appTagline")}</span>
        </span>
      )}
    </span>
  );
}
