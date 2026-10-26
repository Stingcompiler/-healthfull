import { Link, useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { ArrowBack } from "@/components/icons";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";
import { formatDate } from "@/lib/format";
import { useDocumentTitle } from "@/lib/hooks/use-document-title";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

import { useReferralPrint } from "../api";
import { ClinicDocument } from "../print/ClinicDocument";
import { ClinicPrintFrame, type PrintLang } from "../print/ClinicPrintFrame";
import { parseClinicPrintSearch } from "../print/search";
import type { ReferralPrint } from "../types";

function ReferralBody({ data, lang }: { data: ReferralPrint; lang: PrintLang }) {
  const { i18n } = useTranslation();
  const t = i18n.getFixedT(lang, "clinic");
  const r = data.referral;
  const name = (ar: string, en: string) => pickName({ ar, en }, lang);
  const to =
    r.kind === "external"
      ? r.external_facility
      : [
          r.to_department ? name(r.to_department.name_ar, r.to_department.name_en) : "",
          r.to_doctor ? name(r.to_doctor.name_ar, r.to_doctor.name_en) : "",
        ]
          .filter(Boolean)
          .join(" · ");
  return (
    <section className="flex flex-col gap-3" data-testid="print-referral">
      <dl className="grid gap-1">
        <div className="flex flex-wrap gap-x-2">
          <dt className="text-muted">{t("print.referTo")}</dt>
          <dd className="font-semibold break-words">{to}</dd>
        </div>
        <div className="flex flex-wrap gap-x-2">
          <dt className="text-muted">{t("referral.urgencyLabel")}</dt>
          <dd className="font-medium">{t(`referral.urgency.${r.urgency}`)}</dd>
        </div>
        <div className="flex flex-wrap gap-x-2">
          <dt className="text-muted">{t("print.date")}</dt>
          <dd className="font-medium">{formatDate(r.created_at, lang)}</dd>
        </div>
      </dl>
      <p>{t("print.referralGreeting")}</p>
      <div className="flex flex-col gap-1">
        <h2 className="text-base font-semibold">{t("referral.reason")}</h2>
        <p className="whitespace-pre-line">{r.reason}</p>
      </div>
      {r.clinical_summary ? (
        <div className="flex flex-col gap-1">
          <h2 className="text-base font-semibold">{t("referral.summary")}</h2>
          <p className="whitespace-pre-line">{r.clinical_summary}</p>
        </div>
      ) : null}
      <p>{t("print.referralClosing")}</p>
    </section>
  );
}

/** A referral letter as an A4 page in Arabic or English (FEATURES 3.9, inspection F03). */
export function ReferralPrintPage() {
  const { t, i18n } = useTranslation(["clinic", "errors"]);
  const translateError = useTranslateError();
  const uiLanguage = useLanguage();
  const navigate = useNavigate();
  const { referralId } = useParams({ strict: false });
  const search = parseClinicPrintSearch(useSearch({ strict: false }));
  const lang: PrintLang = search.lang ?? uiLanguage;
  const id = Number(referralId);
  const data = useReferralPrint(id);
  useDocumentTitle(t("print.referralTitle"));

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader
        title={t("print.referralTitle")}
        description={t("print.pageDescription")}
        className="print:hidden"
        actions={
          data.data ? (
            <Button asChild variant="outline">
              <Link to="/clinic">
                <ArrowBack aria-hidden="true" />
                {t("print.backToClinic")}
              </Link>
            </Button>
          ) : null
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
          testId="referral-print"
          onLangChange={(next) => {
            void navigate({
              to: "/clinic/referrals/$referralId/print",
              params: { referralId: String(id) },
              search: { lang: next },
              replace: true,
            });
          }}
        >
          <ClinicDocument
            data={data.data}
            lang={lang}
            title={i18n.getFixedT(lang, "clinic")("print.referralHeading")}
            signer={data.data.referral.referred_by}
          >
            <ReferralBody data={data.data} lang={lang} />
          </ClinicDocument>
        </ClinicPrintFrame>
      )}
    </div>
  );
}
