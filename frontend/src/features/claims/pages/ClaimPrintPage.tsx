import "@/features/cashier/components/print.css";

import { Link, useParams } from "@tanstack/react-router";
import { FileText, Printer } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { DateText } from "@/components/DateText";
import { ArrowBack } from "@/components/icons";
import { MoneyText } from "@/components/MoneyText";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";

import { useClaimPrint } from "../api";
import { Period } from "../components/Period";
import { useClaimNames } from "../lib/names";
import type { ClaimPrint } from "../types";

/** The signature lines under the claim. */
const SIGNATURES = ["preparedBy", "approvedBy", "receivedBy"] as const;

/** A4 paper, as the payer files it. */
const PAGE_RULE = "@page { size: A4; margin: 15mm; }";

function Field({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="flex flex-wrap gap-x-2">
      <dt className="text-muted">{label}:</dt>
      <dd className="min-w-0">{children}</dd>
    </div>
  );
}

/** The claim as sent to the payer: the center's letterhead, the payer, and one row per service. */
function ClaimDocument({ data }: { data: ClaimPrint }) {
  const { t } = useTranslation("claims");
  const names = useClaimNames();
  const { center, payer, claim } = data;
  const answered = claim.status === "responded" || claim.status === "closed";
  return (
    <div className="flex flex-col gap-4" data-testid="claim-print">
      <header className="flex flex-col gap-0.5 border-b border-border pb-3">
        <p className="text-lg font-semibold">{names.text(center.name_ar, center.name_en)}</p>
        {center.address ? <p>{center.address}</p> : null}
        {center.phone ? (
          <p>
            <bdi dir="ltr">{center.phone}</bdi>
          </p>
        ) : null}
        {center.registration_no ? (
          <p className="text-xs text-muted">
            {t("print.registration")}: <bdi>{center.registration_no}</bdi>
          </p>
        ) : null}
        <p className="mt-2 text-base font-semibold">{t("print.title")}</p>
      </header>
      <div className="grid gap-4 sm:grid-cols-2">
        <dl className="grid gap-0.5">
          <Field label={t("print.to")}>
            <span className="font-medium">{names.name(payer)}</span>
          </Field>
          {payer.contract_no ? (
            <Field label={t("print.contract")}>
              <bdi>{payer.contract_no}</bdi>
            </Field>
          ) : null}
          {payer.address ? <Field label={t("print.address")}>{payer.address}</Field> : null}
          {payer.contact_name ? <Field label={t("print.contact")}>{payer.contact_name}</Field> : null}
        </dl>
        <dl className="grid gap-0.5">
          <Field label={t("print.number")}>
            <bdi className="font-medium">{claim.number}</bdi>
          </Field>
          <Field label={t("print.period")}>
            <Period start={claim.period_start} end={claim.period_end} />
          </Field>
          {claim.submitted_at ? (
            <Field label={t("print.submitted")}>
              <DateText value={claim.submitted_at} />
            </Field>
          ) : null}
          <Field label={t("print.lineCount")}>{claim.line_count}</Field>
        </dl>
      </div>
      <div className="min-w-0 overflow-x-auto">
        <table className="w-full min-w-[44rem] border-collapse text-start text-xs print:min-w-0">
          <thead>
            <tr className="border-b border-border text-muted">
              <th className="py-1 pe-2 text-start font-medium">#</th>
              <th className="py-1 pe-2 text-start font-medium">{t("print.patient")}</th>
              <th className="py-1 pe-2 text-start font-medium">{t("print.card")}</th>
              <th className="py-1 pe-2 text-start font-medium">{t("print.invoice")}</th>
              <th className="py-1 pe-2 text-start font-medium">{t("print.service")}</th>
              <th className="py-1 pe-2 text-end font-medium">{t("print.qty")}</th>
              <th className="py-1 pe-2 text-end font-medium">{t("print.claimed")}</th>
              {answered ? (
                <>
                  <th className="py-1 pe-2 text-end font-medium">{t("detail.accepted")}</th>
                  <th className="py-1 text-end font-medium">{t("detail.rejected")}</th>
                </>
              ) : null}
            </tr>
          </thead>
          <tbody>
            {claim.lines.map((l, index) => (
              <tr key={l.id} className="border-b border-border align-top">
                <td className="py-1 pe-2 tabular">{index + 1}</td>
                <td className="py-1 pe-2">
                  {names.person(l.patient)}
                  <bdi className="block text-muted">{l.patient.file_no}</bdi>
                </td>
                <td className="py-1 pe-2">
                  <bdi>{l.card_number}</bdi>
                </td>
                <td className="py-1 pe-2">
                  <bdi>{l.invoice_number}</bdi>
                  <span className="block text-muted">
                    <DateText value={l.approved_on} />
                  </span>
                </td>
                <td className="py-1 pe-2">
                  {names.text(l.description_ar, l.description_en)}
                  {l.pre_approval_ref ? (
                    <span className="block text-muted">
                      {t("build.preApproval")}: <bdi>{l.pre_approval_ref}</bdi>
                    </span>
                  ) : null}
                </td>
                <td className="py-1 pe-2 text-end tabular">{l.quantity}</td>
                <td className="py-1 pe-2 text-end">
                  <MoneyText value={l.amount_claimed} currency={false} />
                </td>
                {answered ? (
                  <>
                    <td className="py-1 pe-2 text-end">
                      <MoneyText value={l.accepted_amount} currency={false} />
                    </td>
                    <td className="py-1 text-end">
                      <MoneyText value={l.rejected_amount} currency={false} />
                    </td>
                  </>
                ) : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <dl className="ms-auto grid w-full max-w-72 gap-0.5 border-t border-border pt-2">
        <div className="flex items-baseline justify-between gap-2 font-semibold">
          <dt>{t("print.total")}</dt>
          <dd>
            <MoneyText value={claim.claimed_total} />
          </dd>
        </div>
        {answered ? (
          <>
            <div className="flex items-baseline justify-between gap-2">
              <dt className="text-muted">{t("detail.accepted")}</dt>
              <dd>
                <MoneyText value={claim.accepted_total} />
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-2">
              <dt className="text-muted">{t("detail.rejected")}</dt>
              <dd>
                <MoneyText value={claim.rejected_total} />
              </dd>
            </div>
          </>
        ) : null}
      </dl>
      <div className="mt-6 grid gap-6 sm:grid-cols-3">
        {SIGNATURES.map((key) => (
          <p key={key} className="border-t border-border pt-1 text-xs text-muted">
            {t(`print.${key}`)}
          </p>
        ))}
      </div>
    </div>
  );
}

/** A claim batch for A4 printing in the payer layout (FEATURES 11.3, 0.10). */
export function ClaimPrintPage() {
  const { t } = useTranslation(["claims", "common", "errors"]);
  const translateError = useTranslateError();
  const { claimId } = useParams({ strict: false });
  const data = useClaimPrint(Number(claimId));
  return (
    <div className="flex min-w-0 flex-col gap-4">
      <style>{PAGE_RULE}</style>
      <PageHeader
        title={t("print.pageTitle")}
        description={t("print.pageDescription")}
        icon={<FileText />}
        className="print:hidden"
        actions={
          <>
            <Button asChild variant="outline">
              <Link to="/claims/$claimId" params={{ claimId: String(claimId) }}>
                <ArrowBack aria-hidden="true" />
                {t("print.back")}
              </Link>
            </Button>
            <Button
              onClick={() => {
                window.print();
              }}
              data-testid="print"
            >
              <Printer aria-hidden="true" />
              {t("common:actions.print")}
            </Button>
          </>
        }
      />
      {data.isPending ? (
        <Skeleton className="mx-auto h-96 w-full max-w-[210mm]" />
      ) : data.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(data.error)}
        </AlertCard>
      ) : (
        <div className="flex min-w-0 justify-center">
          <article
            data-print-root
            data-print-format="a4"
            data-theme="light"
            className="w-full max-w-[210mm] min-w-0 bg-surface p-4 text-sm text-fg shadow-card md:p-10"
          >
            <ClaimDocument data={data.data} />
          </article>
        </div>
      )}
    </div>
  );
}
