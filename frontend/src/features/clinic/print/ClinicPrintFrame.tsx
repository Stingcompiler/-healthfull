// The shared print stylesheet: on a page with a [data-print-root], only that element prints.
import "@/features/cashier/components/print.css";

import { Printer } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";

export type PrintLang = "ar" | "en";

/** A4 with the margins of every other A4 document (lab report, invoice). */
const PAGE_RULE = "@page { size: A4; margin: 15mm; }";

/**
 * An A4 clinic document (prescription, referral letter): the paper language switch and the
 * print button, then the paper, always light as printed on white, in its own language and
 * direction whatever the screen's.
 */
export function ClinicPrintFrame({
  lang,
  onLangChange,
  children,
  testId,
}: {
  lang: PrintLang;
  onLangChange: (lang: PrintLang) => void;
  children: ReactNode;
  testId: string;
}) {
  const { t } = useTranslation("clinic");
  return (
    <div className="flex min-w-0 flex-col gap-4">
      <style>{PAGE_RULE}</style>
      <div className="flex flex-wrap items-center justify-between gap-3 print:hidden">
        <Tabs value={lang} onValueChange={(v) => onLangChange(v === "en" ? "en" : "ar")}>
          <TabsList aria-label={t("print.language")}>
            <TabsTrigger value="ar" lang="ar" data-testid="print-lang-ar">
              {t("print.arabic")}
            </TabsTrigger>
            <TabsTrigger value="en" lang="en" data-testid="print-lang-en">
              {t("print.english")}
            </TabsTrigger>
          </TabsList>
        </Tabs>
        <Button onClick={() => window.print()} data-testid="print">
          <Printer aria-hidden="true" />
          {t("print.print")}
        </Button>
      </div>
      <div className="flex min-w-0 justify-center">
        <article
          data-print-root
          data-print-format="a4"
          data-theme="light"
          data-testid={testId}
          lang={lang}
          dir={lang === "ar" ? "rtl" : "ltr"}
          className="w-full max-w-[210mm] min-w-0 bg-surface p-4 text-sm text-fg shadow-card sm:p-6 md:p-10"
        >
          {children}
        </article>
      </div>
    </div>
  );
}
