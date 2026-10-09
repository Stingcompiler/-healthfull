import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { PatientCard, type PatientCardPatient } from "@/components/PatientCard";

import { useNames } from "../lib/use-names";
import type { NameRef, PatientSummary } from "../types";

/** The shared patient card's data from a cashier patient summary and the visit's payer. */
function cardPatient(patient: PatientSummary, payer: NameRef | null | undefined): PatientCardPatient {
  return {
    nameAr: patient.full_name_ar,
    nameEn: patient.full_name_en || null,
    fileNo: patient.file_no,
    sex: patient.sex === "female" ? "female" : "male",
    birthDate: patient.date_of_birth ?? null,
    phone: patient.phone || null,
    coverage: payer ? { nameAr: payer.name_ar, nameEn: payer.name_en } : null,
    incomplete: patient.is_incomplete,
  };
}

/**
 * The patient and visit a cashier screen works on: the shared patient card (both names, age
 * and sex to confirm identity, phone, coverage) with the visit number and department under it.
 */
export function VisitPatientCard({
  patient,
  visitNumber,
  department,
  payer,
  actions,
  children,
  className,
}: {
  patient: PatientSummary;
  visitNumber?: string;
  department?: NameRef | null;
  payer?: NameRef | null;
  actions?: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  const { t } = useTranslation("cashier");
  const names = useNames();
  return (
    <PatientCard patient={cardPatient(patient, payer)} actions={actions} compact className={className}>
      {visitNumber || department ? (
        <dl className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted" data-testid="patient-header">
          {visitNumber ? (
            <div className="flex items-center gap-1">
              <dt>{t("billing.visit")}</dt>
              <dd className="tabular font-semibold text-fg">
                <bdi data-testid="visit-number">{visitNumber}</bdi>
              </dd>
            </div>
          ) : null}
          {department ? (
            <div className="flex items-center gap-1">
              <dt className="sr-only">{t("billing.department")}</dt>
              <dd>{names.name(department)}</dd>
            </div>
          ) : null}
        </dl>
      ) : null}
      {children}
    </PatientCard>
  );
}
