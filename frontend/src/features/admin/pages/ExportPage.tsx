import { FileDown, ShieldAlert } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { AlertCard } from "@/components/AlertCard";
import { Button } from "@/components/ui/button";
import { useTranslateError } from "@/lib/api/translate-error";

import { AdminPage } from "../components/AdminPage";
import { useExportData } from "../ops-api";

const TABLES = [
  "patients",
  "visits",
  "invoices",
  "invoice_lines",
  "payments",
  "allocations",
  "stock_moves",
  "claims",
  "claim_lines",
] as const;

/** Hands a downloaded file to the browser's save flow. */
function save(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => {
    URL.revokeObjectURL(url);
  }, 30_000);
}

/**
 * Full data export (FEATURES 13.9): every patient, visit, invoice, payment, allocation, stock
 * move and claim as CSV files in one zip, for the center's own records or a move to another
 * system. Each export is recorded in the audit trail.
 */
export function ExportPage() {
  const { t } = useTranslation(["ops", "admin"]);
  const translateError = useTranslateError();
  const exporting = useExportData();

  const download = async () => {
    try {
      const { blob, name } = await exporting.mutateAsync();
      save(blob, name);
      toast.success(t("export.done"));
    } catch {
      // Shown below from exporting.error.
    }
  };

  return (
    <AdminPage section="export" title={t("admin:sections.export.title")} description={t("export.description")}>
      <section className="card-surface flex flex-col gap-4 p-4 md:p-5" aria-labelledby="export-what">
        <h2 id="export-what" className="text-base font-semibold text-fg">
          {t("export.whatTitle")}
        </h2>
        <ul className="grid grid-cols-1 gap-x-6 gap-y-1.5 text-sm text-fg sm:grid-cols-2 lg:grid-cols-3">
          {TABLES.map((table) => (
            <li key={table} className="flex items-baseline gap-2">
              <span className="size-1.5 shrink-0 translate-y-[-2px] rounded-full bg-primary" aria-hidden="true" />
              <span>
                {t(`export.tables.${table}`)} <bdi className="text-xs text-muted">{`${table}.csv`}</bdi>
              </span>
            </li>
          ))}
        </ul>
        <p className="text-sm text-muted">{t("export.format")}</p>
        <AlertCard variant="warning" title={t("export.sensitiveTitle")} icon={<ShieldAlert />}>
          {t("export.sensitive")}
        </AlertCard>
        <div>
          <Button onClick={() => void download()} loading={exporting.isPending}>
            <FileDown aria-hidden="true" />
            {t("export.download")}
          </Button>
        </div>
        {exporting.isPending ? (
          <p className="text-sm text-muted" role="status">
            {t("export.working")}
          </p>
        ) : null}
        {exporting.isError ? (
          <AlertCard variant="danger" live title={t("export.failed")}>
            {translateError(exporting.error)}
          </AlertCard>
        ) : null}
      </section>
    </AdminPage>
  );
}
