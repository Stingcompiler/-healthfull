import "./print.css";

import { Printer } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { flushSync } from "react-dom";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

export type PrintFormat = "thermal" | "a4";

/**
 * `size` takes one or two lengths or a keyword, never a length with `auto` (the browser drops
 * such a rule). A roll has no fixed height: 297 mm holds a typical receipt on one page and a
 * longer document continues on the next. The thermal width is checked by the e2e print test.
 */
const PAGE_RULES: Record<PrintFormat, string> = {
  thermal: "@page { size: 80mm 297mm; margin: 4mm; }",
  a4: "@page { size: A4; margin: 15mm; }",
};

/**
 * A printable document: a format switch (80 mm thermal roll or A4), a print button, and the
 * paper itself. The paper always uses the light theme, as printed on white.
 */
export function PrintFrame({
  children,
  toolbar,
}: {
  children: (format: PrintFormat) => ReactNode;
  toolbar?: ReactNode;
}) {
  const { t } = useTranslation(["cashier", "common"]);
  const [format, setFormat] = useState<PrintFormat>("thermal");
  return (
    <div className="flex min-w-0 flex-col gap-4">
      <style>{PAGE_RULES[format]}</style>
      <div className="flex flex-wrap items-center justify-between gap-3 print:hidden">
        <Tabs
          value={format}
          onValueChange={(v) => {
            setFormat(v as PrintFormat);
          }}
        >
          <TabsList aria-label={t("print.format")}>
            <TabsTrigger value="thermal" data-testid="format-thermal">
              {t("print.thermal")}
            </TabsTrigger>
            <TabsTrigger value="a4" data-testid="format-a4">
              {t("print.a4")}
            </TabsTrigger>
          </TabsList>
        </Tabs>
        <div className="flex flex-wrap items-center gap-2">
          {toolbar}
          <Button
            onClick={() => {
              window.print();
            }}
            data-testid="print"
          >
            <Printer aria-hidden="true" />
            {t("common:actions.print")}
          </Button>
        </div>
      </div>
      <div className="flex min-w-0 justify-center">
        <article
          data-print-root
          data-print-format={format}
          data-theme="light"
          className={cn(
            "min-w-0 bg-surface text-fg shadow-card",
            format === "thermal"
              ? "w-full max-w-[80mm] p-3 text-[12px] leading-snug"
              : "w-full max-w-[210mm] p-6 text-sm md:p-10",
          )}
        >
          {children(format)}
        </article>
      </div>
    </div>
  );
}

/**
 * Marks the part of a screen that prints (the shift report): everything else on the page is
 * hidden on paper. On screen it follows the app theme; while printing it switches to the light
 * theme, as printed on white.
 */
export function PrintArea({ children, className }: { children: ReactNode; className?: string }) {
  const [printing, setPrinting] = useState(false);
  useEffect(() => {
    const before = () => {
      flushSync(() => {
        setPrinting(true);
      });
    };
    const after = () => {
      setPrinting(false);
    };
    window.addEventListener("beforeprint", before);
    window.addEventListener("afterprint", after);
    return () => {
      window.removeEventListener("beforeprint", before);
      window.removeEventListener("afterprint", after);
    };
  }, []);
  return (
    <div
      data-print-root
      data-print-format="a4"
      data-theme={printing ? "light" : undefined}
      className={cn("min-w-0", printing && "bg-surface text-fg", className)}
    >
      <style>{PAGE_RULES.a4}</style>
      {children}
    </div>
  );
}
