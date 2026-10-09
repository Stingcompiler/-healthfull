import { Link, useParams } from "@tanstack/react-router";
import { BadgeCheck, Ban, FilePenLine, FlaskConical, Printer, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { DateText } from "@/components/DateText";
import { ArrowBack } from "@/components/icons";
import { PageHeader } from "@/components/PageHeader";
import { PatientCard } from "@/components/PatientCard";
import { ReasonDialog } from "@/components/ReasonDialog";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";
import { usePermission } from "@/lib/auth/hooks";

import { useAmendResults, useApproveResults, useLabReasons, useLabResult } from "../api";
import { StageBadge } from "../components/badges";
import { CancelTestDialog } from "../components/CancelTestDialog";
import { LabNav } from "../components/LabNav";
import { ResultEntryForm } from "../components/ResultEntryForm";
import { ResultValues } from "../components/ResultValues";
import { SamplePanel } from "../components/SamplePanel";
import { VersionHistory } from "../components/VersionHistory";
import { isCritical } from "../lib/flags";
import { useLabNames } from "../lib/use-lab-names";
import type { LabResult } from "../types";

function sexOf(sex: string): "male" | "female" | "unknown" {
  return sex === "male" || sex === "female" ? sex : "unknown";
}

/**
 * One test on the bench (FEATURES 9.2-9.7): its sample, result entry with live flags, the
 * supervisor's approval, the version history, amendment and cancellation.
 */
export function ResultPage() {
  const { t } = useTranslation(["lab", "errors"]);
  const translateError = useTranslateError();
  const { lineId } = useParams({ strict: false });
  const id = Number(lineId);
  const result = useLabResult(id);

  return (
    <div className="flex min-w-0 flex-col gap-4">
      {result.data ? (
        <Header result={result.data} />
      ) : (
        <PageHeader title={t("result.title")} icon={<FlaskConical />} actions={<BackButton />} />
      )}
      <LabNav />
      {result.isPending ? (
        <Skeleton className="h-96" />
      ) : result.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(result.error)}
        </AlertCard>
      ) : (
        <Bench result={result.data} />
      )}
    </div>
  );
}

function BackButton() {
  const { t } = useTranslation("lab");
  return (
    <Button asChild variant="outline">
      <Link to="/lab">
        <ArrowBack aria-hidden="true" />
        {t("result.back")}
      </Link>
    </Button>
  );
}

function Header({ result }: { result: LabResult }) {
  const { t } = useTranslation("lab");
  const names = useLabNames();
  const canPrint = usePermission("lab.print_results");
  const approved = result.versions.some((v) => v.status === "approved");
  return (
    <PageHeader
      title={names.test(result.test)}
      documentTitle={`${names.test(result.test)} · ${names.patient(result.patient)}`}
      eyebrow={
        <span className="flex flex-wrap items-center gap-2">
          <bdi>{result.test.code}</bdi>
          <span aria-hidden="true">·</span>
          <bdi>{result.line.visit_number}</bdi>
        </span>
      }
      icon={<FlaskConical />}
      actions={
        <>
          <StageBadge stage={result.stage} />
          {canPrint && approved ? (
            <Button asChild variant="outline">
              <Link
                to="/lab/results/$lineId/print"
                params={{ lineId: String(result.line.id) }}
                data-testid="print-result"
              >
                <Printer aria-hidden="true" />
                {t("result.print")}
              </Link>
            </Button>
          ) : null}
          <BackButton />
        </>
      }
    />
  );
}

function Bench({ result }: { result: LabResult }) {
  const { t } = useTranslation(["lab", "common", "errors"]);
  const names = useLabNames();
  const canEnter = usePermission("lab.enter_results");
  const canApprove = usePermission("lab.approve_results");
  const canAmend = usePermission("lab.amend_results");
  const canCancel = usePermission("lab.cancel_test");
  const [dirty, setDirty] = useState(false);
  const [amending, setAmending] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [approving, setApproving] = useState(false);
  const approve = useApproveResults(result.line.id);
  const amend = useAmendResults(result.line.id);
  const amendReasons = useLabReasons("result_amend", amending);

  const draft = result.versions.find((v) => v.status === "draft");
  const current = result.versions.find((v) => v.status === "approved");
  const sampleIn = result.sample?.status === "received";
  const amendment = draft !== undefined && draft.amends_version_no !== null;
  // A first result is entered by the bench; a correction of an approved one only by an amender.
  const entering = !amendment && canEnter && sampleIn && (result.stage === "to_enter" || result.stage === "to_approve");
  const editingAmendment = amendment && canAmend;
  const showForm = entering || editingAmendment;
  const criticals = (draft?.values ?? []).filter((v) => isCritical(v.flag));
  const open = result.stage !== "done" && result.stage !== "cancelled";

  return (
    <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(0,1fr)_22rem] lg:items-start">
      <div className="flex min-w-0 flex-col gap-4 lg:order-2">
        <PatientCard
          compact
          patient={{
            nameAr: result.patient.full_name_ar,
            nameEn: result.patient.full_name_en,
            fileNo: result.patient.file_no,
            sex: sexOf(result.patient.sex),
            birthDate: result.patient.date_of_birth,
          }}
        >
          <p className="text-xs text-muted">
            {t("result.orderedBy", { name: names.user(result.line.ordered_by) })} ·{" "}
            <DateText value={result.line.ordered_at} format="datetime" />
          </p>
          {result.line.authorized ? <p className="text-xs text-info-fg">{t("result.authorized")}</p> : null}
        </PatientCard>
        <SamplePanel result={result} />
        {(canCancel && open) || (canAmend && result.stage === "done" && !draft) ? (
          <section className="card-surface flex flex-col gap-2 p-4" data-testid="result-actions">
            {canAmend && result.stage === "done" && !draft ? (
              <Button
                variant="outline"
                onClick={() => {
                  setAmending(true);
                }}
                data-testid="amend-result"
              >
                <FilePenLine aria-hidden="true" />
                {t("result.amend")}
              </Button>
            ) : null}
            {canCancel && open ? (
              <Button
                variant="destructive-soft"
                onClick={() => {
                  setCancelling(true);
                }}
                data-testid="cannot-perform"
              >
                <Ban aria-hidden="true" />
                {t("result.cannotPerform")}
              </Button>
            ) : null}
          </section>
        ) : null}
      </div>

      <div className="flex min-w-0 flex-col gap-4 lg:order-1">
        {result.stage === "cancelled" ? (
          <div data-testid="cancelled-notice">
            <AlertCard variant="warning" title={t("result.cancelledTitle")}>
              {names.reason(result.line.cancel_reason)}
              {result.line.cancel_note ? ` · ${result.line.cancel_note}` : ""}
              {result.line.billing_status === "credited" ? (
                <span className="mt-1 block">{t("result.refundOpened")}</span>
              ) : null}
            </AlertCard>
          </div>
        ) : null}
        {result.stage === "to_collect" || result.stage === "to_receive" ? (
          <AlertCard variant="info" title={t("result.waitingSample")}>
            {t("result.waitingSampleHint")}
          </AlertCard>
        ) : null}

        {showForm ? (
          <section className="card-surface flex min-w-0 flex-col gap-3 p-4 md:p-5">
            <h2 className="text-base font-semibold">
              {draft?.amends_version_no ? t("entry.amendTitle", { number: draft.version_no }) : t("entry.title")}
            </h2>
            <ResultEntryForm key={draft?.revision ?? "new"} result={result} onDirtyChange={setDirty} />
          </section>
        ) : draft && open ? (
          <section className="card-surface flex min-w-0 flex-col gap-3 p-4 md:p-5">
            <h2 className="text-base font-semibold">{t("entry.title")}</h2>
            <ResultValues values={draft.values} />
          </section>
        ) : null}

        {draft && result.stage === "to_approve" && canApprove ? (
          <section
            className="card-surface flex min-w-0 flex-col gap-3 border-warning-border p-4 md:p-5"
            data-testid="approval-panel"
          >
            <h2 className="flex items-center gap-2 text-base font-semibold">
              <BadgeCheck className="size-4 text-muted" aria-hidden="true" />
              {draft.amends_version_no ? t("approve.amendTitle") : t("approve.title")}
            </h2>
            <p className="text-sm text-muted">{t("approve.hint")}</p>
            {criticals.length > 0 ? (
              <AlertCard variant="danger" title={t("approve.criticalTitle")} icon={<TriangleAlert />}>
                {names.list(criticals.map((v) => `${names.text(v.name_ar, v.name_en)} ${v.value}`))}
              </AlertCard>
            ) : null}
            {dirty ? <p className="text-xs text-warning-fg">{t("approve.saveFirst")}</p> : null}
            <div>
              <Button
                disabled={dirty || draft.revision === null}
                onClick={() => {
                  setApproving(true);
                }}
                data-testid="approve-result"
              >
                <BadgeCheck aria-hidden="true" />
                {t("approve.submit")}
              </Button>
            </div>
          </section>
        ) : null}

        {current && result.stage !== "to_approve" ? (
          <section className="card-surface flex min-w-0 flex-col gap-3 p-4 md:p-5" data-testid="current-result">
            <h2 className="text-base font-semibold">{t("result.current")}</h2>
            <ResultValues values={current.values} />
            {current.comment ? <p className="text-sm text-fg-muted">{current.comment}</p> : null}
          </section>
        ) : null}

        <VersionHistory result={result} showDraft={false} />
      </div>

      <ConfirmDialog
        open={approving}
        onOpenChange={setApproving}
        title={t("approve.confirmTitle")}
        description={t("approve.confirmDescription")}
        confirmLabel={t("approve.submit")}
        onConfirm={async () => {
          if (draft?.revision) await approve.mutateAsync(draft.revision);
        }}
      />
      <ReasonDialog
        open={amending}
        onOpenChange={setAmending}
        title={t("amend.title")}
        description={t("amend.description")}
        reasons={(amendReasons.data ?? []).map((r) => ({ code: r.code, label: names.reason(r) }))}
        noteRequired
        confirmLabel={t("amend.confirm")}
        onSubmit={async ({ code, note }) => {
          await amend.mutateAsync({ reason: code, note });
        }}
      />
      <CancelTestDialog result={result} open={cancelling} onOpenChange={setCancelling} />
    </div>
  );
}
