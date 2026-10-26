import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { ArrowBack } from "@/components/icons";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";
import { useDocumentTitle } from "@/lib/hooks/use-document-title";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

import { usePrescriptionPrint } from "../api";
import { ClinicDocument } from "../print/ClinicDocument";
import { ClinicPrintFrame, type PrintLang } from "../print/ClinicPrintFrame";
import { parseClinicPrintSearch } from "../print/search";
import type { PrescriptionPrint } from "../types";

function PrescriptionBody({ data, lang }: { data: PrescriptionPrint; lang: PrintLang }) {
  const { i18n } = useTranslation();
  const t = i18n.getFixedT(lang, "clinic");
  const how = (item: PrescriptionPrint["items"][number]) =>
    [
      item.dose,
      t(`route.${item.route}`, { defaultValue: item.route }),
      item.frequency_code ? t(`frequency.${item.frequency_code}`, { defaultValue: item.frequency_code }) : "",
      item.duration_days ? t("rx.days", { count: item.duration_days }) : "",
      item.as_needed ? t("rx.asNeeded") : "",
    ]
      .filter(Boolean)
      .join(" · ");
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-base font-semibold">{t("print.rxHeading")}</h2>
      <ol className="flex flex-col gap-3">
        {data.items.map((item, index) => (
          <li
            key={item.line_id}
            className="flex flex-col gap-0.5 border-b border-border pb-2"
            data-testid="print-rx-item"
          >
            <p className="font-semibold">
              <span className="num">{index + 1}.</span> {pickName({ ar: item.name_ar, en: item.name_en }, lang)}
            </p>
            <p>{how(item)}</p>
            <p className="text-muted">
              {t("print.quantity")}: <span className="num">{item.quantity}</span>
            </p>
            {item.instructions ? <p>{item.instructions}</p> : null}
          </li>
        ))}
      </ol>
    </section>
  );
}

/** The visit's prescription as an A4 page in Arabic or English (FEATURES 3.5, inspection F03). */
export function PrescriptionPrintPage() {
  const { t, i18n } = useTranslation(["clinic", "errors"]);
  const translateError = useTranslateError();
  const uiLanguage = useLanguage();
  const navigate = useNavigate();
  const { visitId } = useParams({ strict: false });
  const search = parseClinicPrintSearch(useSearch({ strict: false }));
  const lang: PrintLang = search.lang ?? uiLanguage;
  const id = Number(visitId);
  const data = usePrescriptionPrint(id);
  useDocumentTitle(t("print.prescriptionTitle"));

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader
        title={t("print.prescriptionTitle")}
        description={t("print.pageDescription")}
        className="print:hidden"
        actions={
          <Button asChild variant="outline">
            <Link to="/clinic/visits/$visitId" params={{ visitId: String(id) }}>
              <ArrowBack aria-hidden="true" />
              {t("print.back")}
            </Link>
          </Button>
        }
      />
      {data.isPending ? (
        <Skeleton className="mx-auto h-96 w-full max-w-[210mm]" />
      ) : data.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(data.error)}
        </AlertCard>
      ) : (
        <ClinicPrintFrame
          lang={lang}
          testId="prescription-print"
          onLangChange={(next) => {
            void navigate({
              to: "/clinic/visits/$visitId/prescription/print",
              params: { visitId: String(id) },
              search: { lang: next },
              replace: true,
            });
          }}
        >
          <ClinicDocument
            data={data.data}
            lang={lang}
            title={i18n.getFixedT(lang, "clinic")("print.prescriptionHeading")}
            signer={data.data.prescriber ?? data.data.doctor}
          >
            <PrescriptionBody data={data.data} lang={lang} />
          </ClinicDocument>
        </ClinicPrintFrame>
      )}
    </div>
  );
}
