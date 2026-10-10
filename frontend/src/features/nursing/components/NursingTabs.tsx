import { Link } from "@tanstack/react-router";
import { BedDouble, HeartPulse, Syringe, type LucideIcon } from "lucide-react";
import { useTranslation } from "react-i18next";

import { usePermission } from "@/lib/auth/hooks";
import { cn } from "@/lib/utils";

type Section = "procedures" | "visits" | "beds";

const SECTIONS: readonly { id: Section; to: "/nursing" | "/nursing/visits" | "/nursing/beds"; icon: LucideIcon }[] = [
  { id: "procedures", to: "/nursing", icon: Syringe },
  { id: "visits", to: "/nursing/visits", icon: HeartPulse },
  { id: "beds", to: "/nursing/beds", icon: BedDouble },
];

/** The three nursing sections as large links (tablet first); each shows only to who may use it. */
export function NursingTabs({ current }: { current: Section }) {
  const { t } = useTranslation("nursing");
  const allowed: Record<Section, boolean> = {
    procedures: usePermission("orders.perform_procedure"),
    visits: usePermission("clinical.view"),
    beds: usePermission("visits.view"),
  };
  const visible = SECTIONS.filter((s) => allowed[s.id]);
  if (visible.length < 2) return null;
  return (
    <nav aria-label={t("tabs.label")}>
      <ul
        className="grid gap-1 border-b border-border sm:flex sm:gap-2"
        style={{ gridTemplateColumns: `repeat(${String(visible.length)}, minmax(0, 1fr))` }}
      >
        {visible.map(({ id, to, icon: Icon }) => {
          const active = id === current;
          return (
            <li key={id}>
              <Link
                to={to}
                aria-current={active ? "page" : undefined}
                data-testid={`nursing-tab-${id}`}
                className={cn(
                  "-mb-px flex min-h-12 flex-col items-center justify-center gap-1 rounded-t-control border-b-2 px-2 py-1.5 text-center text-xs leading-tight font-medium focus-ring sm:flex-row sm:gap-2 sm:px-4 sm:text-sm",
                  active
                    ? "border-primary text-primary-strong"
                    : "border-transparent text-muted hover:border-border-strong hover:text-fg",
                )}
              >
                <Icon className="size-4" aria-hidden="true" />
                {t(`tabs.${id}`)}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
