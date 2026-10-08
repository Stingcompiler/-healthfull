import { useTranslation } from "react-i18next";

import { ChevronNext, ChevronPrev } from "@/components/icons";
import { Button } from "@/components/ui/button";

/** Server-side pages of a cashier queue (`{items, count, page, page_size}`). */
export function Pager({
  page,
  pageSize,
  count,
  onPage,
}: {
  page: number;
  pageSize: number;
  count: number;
  onPage: (page: number) => void;
}) {
  const { t } = useTranslation(["cashier", "common"]);
  const pages = Math.max(1, Math.ceil(count / pageSize));
  if (pages <= 1) return null;
  return (
    <nav className="flex items-center justify-end gap-2 text-sm" aria-label={t("pager.label")}>
      <Button
        variant="outline"
        size="sm"
        disabled={page <= 1}
        onClick={() => {
          onPage(page - 1);
        }}
      >
        <ChevronPrev aria-hidden="true" />
        {t("common:actions.previous")}
      </Button>
      <span className="text-muted tabular">{t("pager.pageOf", { page, pages })}</span>
      <Button
        variant="outline"
        size="sm"
        disabled={page >= pages}
        onClick={() => {
          onPage(page + 1);
        }}
      >
        {t("common:actions.next")}
        <ChevronNext aria-hidden="true" />
      </Button>
    </nav>
  );
}
