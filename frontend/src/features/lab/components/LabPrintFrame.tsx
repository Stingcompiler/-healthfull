// The cashier's print stylesheet: on a page with a [data-print-root], only that element prints.
import "@/features/cashier/components/print.css";

import { Printer } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type LabPaper = "a4" | "label";

/** `@page` per paper: an A4 report, or a 50 x 30 mm tube label on a label printer. */
const PAGE_RULES: Record<LabPaper, string> = {
  a4: "@page { size: A4; margin: 15mm; }",
  label: "@page { size: 50mm 30mm; margin: 1.5mm; }",
};

/**
 * A printable lab document (the result report or a tube label): a toolbar with a print button
 * and the paper itself, always in the light theme as printed on white. The paper may carry its
 * own language and direction (a report printed in English from an Arabic screen).
 */
export function LabPrintFrame({
  paper,
  lang,
  dir,
  toolbar,
  onPrint,
  children,
  testId,
}: {
  paper: LabPaper;
  lang?: string;
  dir?: "rtl" | "ltr";
  toolbar?: ReactNode;
  /** Called before the browser's print dialog opens (e.g. to record that a label was printed). */
  onPrint?: () => void;
  children: ReactNode;
  testId?: string;
}) {
  const { t } = useTranslation("common");
  return (
    <div className="flex min-w-0 flex-col gap-4">
      <style>{PAGE_RULES[paper]}</style>
      <div className="flex flex-wrap items-center justify-between gap-3 print:hidden">
        <div className="flex min-w-0 flex-wrap items-center gap-2">{toolbar}</div>
        <Button
          onClick={() => {
            onPrint?.();
            window.print();
          }}
          data-testid="print"
        >
          <Printer aria-hidden="true" />
          {t("actions.print")}
        </Button>
      </div>
      <div className="flex min-w-0 justify-center">
        <article
          data-print-root
          data-print-format={paper === "a4" ? "a4" : "label"}
          data-theme="light"
          data-testid={testId}
          lang={lang}
          dir={dir}
          className={cn(
            "min-w-0 bg-surface text-fg shadow-card",
            paper === "a4"
              ? "w-full max-w-[210mm] p-4 text-sm sm:p-6 md:p-10"
              : "w-full max-w-[50mm] overflow-hidden rounded-control border border-border p-1.5 text-[10px] leading-tight",
          )}
        >
          {children}
        </article>
      </div>
    </div>
  );
}
