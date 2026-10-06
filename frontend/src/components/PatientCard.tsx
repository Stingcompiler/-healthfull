import { Phone, ShieldCheck, TriangleAlert, UserRound } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { ageFromBirthDate } from "@/lib/age";
import { useLanguage } from "@/lib/i18n-hooks";
import { initials, pickName } from "@/lib/names";
import { cn } from "@/lib/utils";

export interface PatientCardPatient {
  nameAr: string;
  nameEn?: string | null;
  fileNo: string;
  sex: "male" | "female";
  /** ISO date (YYYY-MM-DD); preferred over ageYears when known. */
  birthDate?: string | null;
  /** Estimated age when only age was recorded. */
  ageYears?: number | null;
  phone?: string | null;
  /** null = not recorded yet; [] = no known allergies. */
  allergies: readonly string[] | null;
  /** Payer for this visit/file; null = self-pay (cash). */
  coverage?: { nameAr: string; nameEn?: string | null; cardNo?: string | null } | null;
  /** Emergency file registered with name and sex only. */
  incomplete?: boolean;
}

export interface PatientCardProps {
  patient: PatientCardPatient;
  actions?: ReactNode;
  /** Dense variant for lists and side panels. */
  compact?: boolean;
  className?: string;
}

export function PatientCard({ patient, actions, compact = false, className }: PatientCardProps) {
  const { t } = useTranslation();
  const language = useLanguage();
  const name = pickName({ ar: patient.nameAr, en: patient.nameEn }, language);
  const otherName = language === "ar" ? patient.nameEn : patient.nameAr;
  const age = patient.birthDate ? ageFromBirthDate(patient.birthDate) : null;
  const ageText = age
    ? age.years >= 1
      ? t("patient.years", { count: age.years })
      : t("patient.months", { count: age.months })
    : patient.ageYears != null
      ? t("patient.years", { count: patient.ageYears })
      : null;
  const allergies = patient.allergies;

  return (
    <article
      data-slot="patient-card"
      className={cn("card-surface flex min-w-0 flex-col", compact ? "gap-3 p-3 md:p-4" : "gap-4 p-4 md:p-5", className)}
    >
      <div className="flex min-w-0 items-start gap-3">
        <Avatar className={compact ? "size-10" : "size-12"}>
          <AvatarFallback className="text-base">{initials(name) || <UserRound className="size-5" />}</AvatarFallback>
        </Avatar>
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-base leading-snug font-semibold text-fg">{name}</h3>
          {otherName && otherName !== name ? (
            <p className="truncate text-sm text-muted" lang={language === "ar" ? "en" : "ar"}>
              {otherName}
            </p>
          ) : null}
          <dl className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
            <div className="flex items-center gap-1">
              <dt>{t("patient.fileNo")}</dt>
              <dd className="tabular font-semibold text-fg">
                <bdi>{patient.fileNo}</bdi>
              </dd>
            </div>
            {ageText ? (
              <div className="flex items-center gap-1">
                <dt className="sr-only">{t("patient.age")}</dt>
                <dd>{ageText}</dd>
              </div>
            ) : null}
            <div className="flex items-center gap-1">
              <dt className="sr-only">{t("patient.sex")}</dt>
              <dd>{t(`sex.${patient.sex}`)}</dd>
            </div>
            {patient.phone ? (
              <div className="flex items-center gap-1">
                <dt>
                  <Phone className="size-3.5" aria-hidden="true" />
                  <span className="sr-only">{t("patient.phone")}</span>
                </dt>
                <dd className="tabular">
                  <bdi>{patient.phone}</bdi>
                </dd>
              </div>
            ) : null}
          </dl>
        </div>
        {actions ? <div className="flex shrink-0 items-center gap-1">{actions}</div> : null}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {allergies === null ? (
          <Badge variant="warning">
            <TriangleAlert aria-hidden="true" />
            {t("patient.allergiesUnknown")}
          </Badge>
        ) : allergies.length === 0 ? (
          <Badge variant="neutral">{t("patient.noKnownAllergies")}</Badge>
        ) : (
          <div role="group" aria-label={t("patient.allergyAlert")} className="flex flex-wrap items-center gap-1.5">
            {allergies.map((allergy) => (
              <span
                key={allergy}
                className="inline-flex items-center gap-1 rounded-full bg-danger px-2.5 py-1 text-xs font-semibold text-danger-contrast"
              >
                <TriangleAlert className="size-3.5" aria-hidden="true" />
                <span className="sr-only">{t("patient.allergies")}: </span>
                {allergy}
              </span>
            ))}
          </div>
        )}
        <Badge variant={patient.coverage ? "info" : "outline"} className="ms-auto">
          <ShieldCheck aria-hidden="true" />
          <span className="sr-only">{t("patient.coverage")}: </span>
          {patient.coverage
            ? pickName({ ar: patient.coverage.nameAr, en: patient.coverage.nameEn }, language)
            : t("patient.cash")}
        </Badge>
        {patient.incomplete ? <Badge variant="warning">{t("patient.incompleteFile")}</Badge> : null}
      </div>
    </article>
  );
}
