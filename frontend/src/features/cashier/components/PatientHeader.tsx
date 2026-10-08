import { Phone, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";

import { useNames } from "../lib/use-names";
import type { NameRef, PatientSummary } from "../types";

/** The patient and visit a cashier screen works on: name, file number, phone, coverage. */
export function PatientHeader({
  patient,
  visitNumber,
  department,
  payer,
  children,
}: {
  patient: PatientSummary;
  visitNumber?: string;
  department?: NameRef | null;
  payer?: NameRef | null;
  children?: ReactNode;
}) {
  const { t } = useTranslation(["cashier", "common"]);
  const names = useNames();
  return (
    <div className="flex min-w-0 flex-col gap-2" data-testid="patient-header">
      <h2 className="text-lg leading-snug font-semibold break-words">{names.patient(patient)}</h2>
      <dl className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted">
        <div className="flex items-center gap-1">
          <dt>{t("common:patient.fileNo")}</dt>
          <dd className="tabular font-semibold text-fg">
            <bdi>{patient.file_no}</bdi>
          </dd>
        </div>
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
        {patient.phone ? (
          <div className="flex items-center gap-1">
            <dt>
              <Phone className="size-3.5" aria-hidden="true" />
              <span className="sr-only">{t("common:patient.phone")}</span>
            </dt>
            <dd className="tabular">
              <bdi>{patient.phone}</bdi>
            </dd>
          </div>
        ) : null}
        <div className="flex items-center gap-1">
          <dt className="sr-only">{t("common:patient.coverage")}</dt>
          <dd>
            <Badge variant={payer ? "info" : "outline"}>
              <ShieldCheck aria-hidden="true" />
              {payer ? names.name(payer) : t("common:patient.cash")}
            </Badge>
          </dd>
        </div>
        {patient.is_incomplete ? <Badge variant="warning">{t("common:patient.incompleteFile")}</Badge> : null}
      </dl>
      {children}
    </div>
  );
}
