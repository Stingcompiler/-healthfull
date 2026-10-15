import { ShieldCheck, TriangleAlert } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";
import { ChevronNext } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { ageFromBirthDate } from "@/lib/age";
import { useDirection, useLanguage } from "@/lib/i18n-hooks";
import { pickName, textDirection } from "@/lib/names";
import { cn } from "@/lib/utils";

import type { PatientCardPatient } from "@/components/PatientCard";

import type { DirLine } from "./data";

export function OpenButton({ className }: { className?: string }) {
  const { t } = useTranslation("dashboard");
  return (
    <Button variant="outline" size="sm" className={className}>
      {t("alerts.open")}
      <ChevronNext aria-hidden="true" />
    </Button>
  );
}

/** Payer / not covered / pre-approval badges of a line. */
export function LineFlags({ line }: { line: DirLine }) {
  const { t } = useTranslation("cashier");
  const language = useLanguage();
  return (
    <>
      <Badge variant={line.payer ? "info" : "neutral"}>
        {line.payer ? pickName(line.payer, language) : t("invoice.cash")}
      </Badge>
      {line.flag === "excluded" ? <Badge variant="warning">{t("invoice.excluded")}</Badge> : null}
      {line.flag === "preapproval" ? <Badge variant="warning">{t("invoice.needsPreapproval")}</Badge> : null}
    </>
  );
}

/**
 * Patient identity as an open strip (no avatar, no surface): name that wraps, file number,
 * age and phone, then the allergy chips (always the loudest thing) and the coverage.
 */
export function PatientStrip({ patient, className }: { patient: PatientCardPatient; className?: string }) {
  const { t } = useTranslation();
  const language = useLanguage();
  const uiDirection = useDirection();
  const name = pickName({ ar: patient.nameAr, en: patient.nameEn }, language);
  const age = patient.birthDate ? ageFromBirthDate(patient.birthDate) : null;
  const dir = textDirection(name, uiDirection);
  return (
    <div className={cn("flex min-w-0 flex-col gap-2", className)}>
      <h3
        dir={dir}
        className={cn(
          "text-base leading-snug font-semibold text-balance break-words text-fg",
          dir === uiDirection ? "text-start" : "text-end",
        )}
      >
        {name}
      </h3>
      <dl className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
        <div className="flex gap-1">
          <dt>{t("patient.fileNo")}</dt>
          <dd className="tabular font-semibold text-fg">
            <bdi>{patient.fileNo}</bdi>
          </dd>
        </div>
        {age ? (
          <div>
            <dt className="sr-only">{t("patient.age")}</dt>
            <dd>{t("patient.years", { count: age.years })}</dd>
          </div>
        ) : null}
        <div>
          <dt className="sr-only">{t("patient.sex")}</dt>
          <dd>{t(`sex.${patient.sex}`)}</dd>
        </div>
        {patient.phone ? (
          <div className="flex gap-1">
            <dt>{t("patient.phone")}</dt>
            <dd className="tabular">
              <bdi dir="ltr">{patient.phone}</bdi>
            </dd>
          </div>
        ) : null}
      </dl>
      <div className="flex flex-wrap items-center gap-1.5">
        {patient.allergies && patient.allergies.length > 0 ? (
          <span role="group" aria-label={t("patient.allergyAlert")} className="flex flex-wrap items-center gap-1.5">
            {patient.allergies.map((allergy) => (
              <span
                key={allergy}
                className="inline-flex items-center gap-1 rounded-full bg-danger px-2.5 py-0.5 text-xs font-semibold text-danger-contrast"
              >
                <TriangleAlert className="size-3.5" aria-hidden="true" />
                <span className="sr-only">{t("patient.allergies")}: </span>
                {allergy}
              </span>
            ))}
          </span>
        ) : null}
        <Badge variant={patient.coverage ? "info" : "outline"}>
          <ShieldCheck aria-hidden="true" />
          <span className="sr-only">{t("patient.coverage")}: </span>
          {patient.coverage
            ? pickName({ ar: patient.coverage.nameAr, en: patient.coverage.nameEn }, language)
            : t("patient.cash")}
        </Badge>
      </div>
    </div>
  );
}
