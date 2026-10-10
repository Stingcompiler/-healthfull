import { Link } from "@tanstack/react-router";
import { ChartColumn, Lock } from "lucide-react";
import { useTranslation } from "react-i18next";

import { EmptyState } from "@/components/EmptyState";
import { ChevronNext } from "@/components/icons";
import { PageHeader } from "@/components/PageHeader";
import { useCurrentUser } from "@/lib/auth/hooks";

import { AREA_ICONS, REPORT_AREAS, REPORT_CATALOG } from "../catalog";

/**
 * The report catalog (FEATURES 12.x): the reports the user may open, grouped by area. Each
 * card opens the report with its filters, Excel export and print view.
 */
export function ReportsPage() {
  const { t } = useTranslation("reports");
  const me = useCurrentUser();
  const held = new Set(me?.permissions ?? []);
  const isAdmin = me?.roles.includes("admin") ?? false;
  const visible = REPORT_CATALOG.filter((r) => isAdmin || held.has(r.permission));

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <PageHeader title={t("title")} description={t("description")} icon={<ChartColumn />} />
      {visible.length === 0 ? (
        <EmptyState icon={<Lock />} title={t("empty.title")} description={t("empty.description")} />
      ) : (
        REPORT_AREAS.map((area) => {
          const reports = visible.filter((r) => r.area === area);
          if (reports.length === 0) return null;
          const AreaIcon = AREA_ICONS[area];
          return (
            <section
              key={area}
              aria-labelledby={`area-${area}`}
              className="flex flex-col gap-3"
              data-testid={`area-${area}`}
            >
              <div className="flex items-center gap-2">
                <AreaIcon className="size-5 text-primary-strong" aria-hidden="true" />
                <h2 id={`area-${area}`} className="text-base font-semibold text-fg">
                  {t(`areas.${area}`)}
                </h2>
              </div>
              <ul className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
                {reports.map((report) => {
                  const Icon = report.icon;
                  return (
                    <li key={report.key} className="min-w-0">
                      <Link
                        to="/reports/$reportKey"
                        params={{ reportKey: report.key }}
                        data-testid={`report-${report.key}`}
                        className="card-surface flex min-h-11 items-start gap-3 p-4 focus-ring transition-colors hover:border-primary/40"
                      >
                        <span className="flex size-10 shrink-0 items-center justify-center rounded-control bg-primary-soft text-primary-strong [&_svg]:size-5">
                          <Icon aria-hidden="true" />
                        </span>
                        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                          <span className="font-semibold text-fg">{t(`catalog.${report.key}.title`)}</span>
                          <span className="text-sm text-pretty text-muted">
                            {t(`catalog.${report.key}.description`)}
                          </span>
                        </span>
                        <ChevronNext className="mt-1 size-4 shrink-0 text-muted" aria-hidden="true" />
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </section>
          );
        })
      )}
    </div>
  );
}
