import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { ageFromBirthDate } from "@/lib/age";
import { useCenterPage } from "@/lib/center/api";
import { formatDate } from "@/lib/format";
import { pickName } from "@/lib/names";

import type { ClinicalPrint } from "../types";
import type { PrintLang } from "./ClinicPrintFrame";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-wrap gap-x-2">
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0 font-medium break-words">{children}</dd>
    </div>
  );
}

/** Lines of a free-text header or footer from the print template, as written. */
function TemplateText({ text, className }: { text: string; className?: string }) {
  if (!text.trim()) return null;
  return <p className={className ?? "whitespace-pre-line"}>{text}</p>;
}

/**
 * The parts every printed clinic document shares: the center's identity and the print
 * template's header, the patient and the visit, allergies and diagnoses, then the document's own
 * body, the doctor's signature line and the template's footer. Never a price.
 */
export function ClinicDocument({
  data,
  lang,
  title,
  signer,
  children,
}: {
  data: ClinicalPrint;
  lang: PrintLang;
  title: string;
  signer: { name_ar: string; name_en: string } | null;
  children: ReactNode;
}) {
  const { i18n } = useTranslation();
  const t = i18n.getFixedT(lang, "clinic");
  const center = useCenterPage();
  const name = (ar: string, en: string) => pickName({ ar, en }, lang);
  const p = data.patient;
  const age = p.date_of_birth ? ageFromBirthDate(p.date_of_birth) : null;
  const logo = data.template.show_logo && data.center.has_logo ? (center.data?.logo_url ?? null) : null;
  const header = lang === "ar" ? data.template.header_ar : data.template.header_en;
  const footer = lang === "ar" ? data.template.footer_ar : data.template.footer_en;

  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-col items-center gap-0.5 border-b border-border pb-3 text-center">
        {logo ? <img src={logo} alt="" className="mb-1 h-14 w-auto object-contain" /> : null}
        <p className="text-lg font-semibold">{name(data.center.name_ar, data.center.name_en)}</p>
        {data.center.address ? <p>{data.center.address}</p> : null}
        {data.center.phone ? (
          <p>
            <bdi dir="ltr" className="num">
              {data.center.phone}
            </bdi>
          </p>
        ) : null}
        <TemplateText text={header} className="mt-1 text-xs whitespace-pre-line" />
        <p className="mt-2 text-base font-semibold" data-testid="print-title">
          {title}
        </p>
      </header>

      <dl className="grid gap-x-6 gap-y-1 sm:grid-cols-2">
        <Field label={t("print.patient")}>{name(p.full_name_ar, p.full_name_en)}</Field>
        <Field label={t("print.fileNo")}>
          <bdi dir="ltr" className="num">
            {p.file_no}
          </bdi>
        </Field>
        <Field label={t("print.sexAge")}>
          {t(`print.sex.${p.sex}`)}
          {age
            ? ` · ${age.years >= 1 ? t("print.years", { count: age.years }) : t("print.months", { count: age.months })}`
            : ""}
        </Field>
        <Field label={t("print.visit")}>
          <bdi dir="ltr" className="num">
            {data.visit_number}
          </bdi>
          {" · "}
          {formatDate(data.visit_date, lang)}
        </Field>
        {data.doctor ? <Field label={t("print.doctor")}>{name(data.doctor.name_ar, data.doctor.name_en)}</Field> : null}
        {data.department ? (
          <Field label={t("print.department")}>{name(data.department.name_ar, data.department.name_en)}</Field>
        ) : null}
      </dl>

      <dl className="grid gap-1">
        <Field label={t("print.allergies")}>
          <span data-testid="print-allergies">
            {data.allergies.length > 0
              ? data.allergies.map((a) => name(a.label_ar, a.label_en)).join(t("print.listSeparator"))
              : t("print.noAllergies")}
          </span>
        </Field>
        {data.diagnoses.length > 0 ? (
          <Field label={t("print.diagnoses")}>
            {data.diagnoses
              .map((d) =>
                d.icd10
                  ? `${d.icd10.code} ${lang === "ar" && d.icd10.title_ar ? d.icd10.title_ar : d.icd10.title_en}`
                  : d.text,
              )
              .join(t("print.groupSeparator"))}
          </Field>
        ) : null}
      </dl>

      {children}

      <footer className="mt-6 flex flex-col gap-2 border-t border-border pt-3 text-xs">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <span>
            {t("print.signedBy")}: {signer ? name(signer.name_ar, signer.name_en) : ""}
          </span>
          <span className="min-w-40 border-b border-border-strong pb-6 text-muted">{t("print.signature")}</span>
        </div>
        <TemplateText text={footer} />
        <span className="text-muted">
          {t("print.printedAt", { at: formatDate(data.printed_at, lang, "datetime") })}
        </span>
      </footer>
    </div>
  );
}
