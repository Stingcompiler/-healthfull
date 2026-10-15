import { Link, useSearch } from "@tanstack/react-router";
import type { ReactElement } from "react";
import { useTranslation } from "react-i18next";

import { PageHeader } from "@/components/PageHeader";
import { cn } from "@/lib/utils";

import { CalmCashier, CalmDashboard } from "./Calm";
import { CurrentCashier, CurrentDashboard } from "./Current";
import { FlatCashier, FlatDashboard } from "./Flat";
import { TintedCashier, TintedDashboard } from "./Tinted";

const DIRECTIONS = ["current", "calm", "flat", "tinted"] as const;
type Direction = (typeof DIRECTIONS)[number];

const PARTS: Record<Direction, { dashboard: () => ReactElement; cashier: () => ReactElement }> = {
  current: { dashboard: CurrentDashboard, cashier: CurrentCashier },
  calm: { dashboard: CalmDashboard, cashier: CalmCashier },
  flat: { dashboard: FlatDashboard, cashier: FlatCashier },
  tinted: { dashboard: TintedDashboard, cashier: TintedCashier },
};

function isDirection(value: unknown): value is Direction {
  return typeof value === "string" && (DIRECTIONS as readonly string[]).includes(value);
}

/**
 * DEV ONLY (UI review, phase 1). The route exists only in the Vite dev server (see routes.tsx);
 * the production bundle does not contain it. `?d=current|calm|flat|tinted` picks the direction.
 * Every candidate renders the same sample data (./data.ts) so they can be compared side by side.
 */
export function DirectionsPage() {
  const { t } = useTranslation("design");
  const search: { d?: unknown } = useSearch({ strict: false });
  const current: Direction = isDirection(search.d) ? search.d : "current";
  const Dashboard = PARTS[current].dashboard;
  const Cashier = PARTS[current].cashier;
  return (
    <div className="flex min-w-0 flex-col gap-8" data-testid="directions" data-direction={current}>
      <PageHeader title={t(`directions.${current}`)} description={t(`directions.${current}Note`)} />
      <nav aria-label={t("directions.title")} className="flex flex-wrap gap-2">
        {DIRECTIONS.map((d) => (
          <Link
            key={d}
            to="/design/directions"
            search={{ d }}
            aria-current={d === current ? "page" : undefined}
            className={cn(
              "rounded-control border px-3 py-1.5 text-sm focus-ring",
              d === current
                ? "border-primary bg-primary-soft font-semibold text-primary-strong"
                : "border-border text-fg",
            )}
          >
            {t(`directions.${d}`)}
          </Link>
        ))}
      </nav>
      <section className="flex min-w-0 flex-col gap-4" aria-labelledby="dir-dashboard">
        <h2 id="dir-dashboard" className="text-sm font-semibold tracking-wide text-muted uppercase">
          {t("directions.dashboardPart")}
        </h2>
        <Dashboard />
      </section>
      <section className="flex min-w-0 flex-col gap-4" aria-labelledby="dir-cashier">
        <h2 id="dir-cashier" className="text-sm font-semibold tracking-wide text-muted uppercase">
          {t("directions.cashierPart")}
        </h2>
        <Cashier />
      </section>
    </div>
  );
}
