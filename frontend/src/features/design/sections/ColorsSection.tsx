import { useTranslation } from "react-i18next";

import { STATUSES } from "@/components/status";
import { StatusBadge } from "@/components/StatusBadge";
import { cn } from "@/lib/utils";

import { Demo, Section } from "../Section";

interface Swatch {
  token: string;
  className: string;
  /** Text color shown on the swatch, to preview the pairing. */
  textClassName?: string;
}

const SURFACES: Swatch[] = [
  { token: "--bg", className: "bg-bg", textClassName: "text-fg" },
  { token: "--surface", className: "bg-surface", textClassName: "text-fg" },
  { token: "--surface-raised", className: "bg-surface-raised", textClassName: "text-fg" },
  { token: "--subtle", className: "bg-subtle", textClassName: "text-fg" },
  { token: "--accent", className: "bg-accent", textClassName: "text-accent-fg" },
];

const TEXT: Swatch[] = [
  { token: "--fg", className: "bg-fg" },
  { token: "--fg-muted", className: "bg-fg-muted" },
  { token: "--border", className: "bg-border" },
  { token: "--border-strong", className: "bg-border-strong" },
  { token: "--ring", className: "bg-ring" },
];

const BRAND: Swatch[] = [
  { token: "--primary", className: "bg-primary", textClassName: "text-primary-fg" },
  { token: "--primary-hover", className: "bg-primary-hover", textClassName: "text-primary-fg" },
  { token: "--primary-strong", className: "bg-primary-strong" },
  { token: "--primary-soft", className: "bg-primary-soft", textClassName: "text-primary-strong" },
  { token: "--secondary", className: "bg-secondary", textClassName: "text-secondary-fg" },
];

const SEMANTIC: Swatch[] = [
  { token: "--success", className: "bg-success", textClassName: "text-success-contrast" },
  { token: "--success-bg", className: "bg-success-bg", textClassName: "text-success-fg" },
  { token: "--warning", className: "bg-warning", textClassName: "text-warning-contrast" },
  { token: "--warning-bg", className: "bg-warning-bg", textClassName: "text-warning-fg" },
  { token: "--danger", className: "bg-danger", textClassName: "text-danger-contrast" },
  { token: "--danger-bg", className: "bg-danger-bg", textClassName: "text-danger-fg" },
  { token: "--info", className: "bg-info", textClassName: "text-info-contrast" },
  { token: "--info-bg", className: "bg-info-bg", textClassName: "text-info-fg" },
];

function SwatchGrid({ swatches }: { swatches: Swatch[] }) {
  const { t } = useTranslation("design");
  return (
    <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
      {swatches.map((s) => (
        <li key={s.token} className="overflow-hidden rounded-card border border-border bg-surface">
          <div className={cn("flex h-16 items-end p-2 text-sm font-semibold", s.className, s.textClassName)}>
            {s.textClassName ? t("colors.sample") : null}
          </div>
          <code className="block truncate px-2 py-1.5 font-mono text-xs text-muted" dir="ltr">
            {s.token}
          </code>
        </li>
      ))}
    </ul>
  );
}

export function ColorsSection() {
  const { t } = useTranslation("design");
  return (
    <Section id="colors" title={t("sections.colors")} description={t("descriptions.colors")}>
      <Demo label={t("colors.surfaces")}>
        <SwatchGrid swatches={SURFACES} />
      </Demo>
      <Demo label={t("colors.text")}>
        <SwatchGrid swatches={TEXT} />
      </Demo>
      <Demo label={t("colors.brand")}>
        <SwatchGrid swatches={BRAND} />
      </Demo>
      <Demo label={t("colors.semantic")}>
        <SwatchGrid swatches={SEMANTIC} />
      </Demo>
      <Demo label={t("colors.states")} className="flex flex-wrap gap-2">
        {STATUSES.map((status) => (
          <StatusBadge key={status} status={status} />
        ))}
      </Demo>
    </Section>
  );
}
