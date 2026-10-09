import { Link, useParams } from "@tanstack/react-router";
import type { ColumnDef } from "@tanstack/react-table";
import {
  Ban,
  CheckCheck,
  FileSpreadsheet,
  FileStack,
  FileX2,
  Lock,
  MessageSquareReply,
  Printer,
  Send,
  Trash2,
  UserRoundPlus,
} from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { DataTable, type DataTableRowAction } from "@/components/DataTable";
import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { ArrowBack } from "@/components/icons";
import { MoneyText } from "@/components/MoneyText";
import { PageHeader } from "@/components/PageHeader";
import { ReasonDialog } from "@/components/ReasonDialog";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { NoteDialog } from "@/features/cashier/components/NoteDialog";
import { useTranslateError } from "@/lib/api/translate-error";
import { usePermission } from "@/lib/auth/hooks";

import {
  exportUrl,
  useClaim,
  useClaimOptions,
  useCloseClaim,
  useRecordResponses,
  useRemoveClaimLine,
  useResolveRejection,
  useSubmitClaim,
  useVoidClaim,
} from "../api";
import { AmountTiles } from "../components/AmountTiles";
import { ClaimStageBadge, ClaimStatusBadge } from "../components/ClaimBadges";
import { ClaimsNav } from "../components/ClaimsNav";
import { Period } from "../components/Period";
import { ResponseDialog } from "../components/ResponseDialog";
import { ShortfallDialog } from "../components/ShortfallDialog";
import { useClaimNames } from "../lib/names";
import type { ClaimDetail, ClaimLine } from "../types";

type Resolution = "rebilled" | "written_off";

const isZero = (v: string) => v === "0.00";

/** Who and what one claim line is: service, patient, card, invoice. */
function LineIdentity({ line }: { line: ClaimLine }) {
  const { t } = useTranslation("claims");
  const names = useClaimNames();
  return (
    <span className="flex min-w-0 flex-col">
      <span className="font-medium">{names.text(line.description_ar, line.description_en)}</span>
      <span className="text-sm">{names.person(line.patient)}</span>
      <span className="flex flex-wrap gap-x-3 text-xs text-muted">
        <bdi>{line.patient.file_no}</bdi>
        {line.card_number ? (
          <span>
            {t("build.card")}: <bdi>{line.card_number}</bdi>
          </span>
        ) : null}
        <bdi>{line.invoice_number}</bdi>
        <DateText value={line.approved_on} />
      </span>
    </span>
  );
}

/** The payer's answer and what became of a rejected part. */
function LineAnswer({ line }: { line: ClaimLine }) {
  const { t } = useTranslation("claims");
  const names = useClaimNames();
  if (line.status === "pending") return <span className="text-sm text-muted">{t("detail.awaiting")}</span>;
  return (
    <span className="flex min-w-0 flex-col gap-0.5 text-sm">
      <span className="flex flex-wrap items-center gap-x-1">
        <span className="text-muted">{t("detail.accepted")}:</span>
        <MoneyText value={line.accepted_amount} currency={false} />
      </span>
      {!isZero(line.rejected_amount) ? (
        <span className="flex flex-wrap items-center gap-x-1">
          <span className="text-muted">{t("detail.rejected")}:</span>
          <MoneyText value={line.rejected_amount} currency={false} />
        </span>
      ) : null}
      {line.payer_reason ? <span className="text-xs text-muted">{line.payer_reason}</span> : null}
      {line.resolution !== "none" ? (
        <span className="text-xs" data-testid="line-resolution">
          {t(`resolution.${line.resolution}`)}
          {line.resolution_reason ? ` · ${names.label(line.resolution_reason)}` : ""}
        </span>
      ) : null}
      {!isZero(line.written_off_amount) ? (
        <span className="flex flex-wrap items-center gap-x-1 text-xs">
          <span>{t("detail.shortfallWrittenOff")}:</span>
          <MoneyText value={line.written_off_amount} currency={false} />
        </span>
      ) : null}
    </span>
  );
}

/**
 * One claim batch (FEATURES 11.3-11.6): its lines with the payer's answers entered per line,
 * rejected parts rebilled to the patient or written off, payments received, and the batch's
 * own steps (submit, void, close), export to Excel and print.
 */
export function ClaimDetailPage() {
  const { t } = useTranslation(["claims", "common", "errors"]);
  const translateError = useTranslateError();
  const names = useClaimNames();
  const { claimId: raw } = useParams({ strict: false });
  const claimId = Number(raw);
  const claim = useClaim(claimId);
  const canManage = usePermission("claims.manage");
  const canRespond = usePermission("claims.record_response");
  const canResolve = usePermission("claims.resolve_rejection");
  const options = useClaimOptions();
  const submit = useSubmitClaim();
  const voidClaim = useVoidClaim();
  const close = useCloseClaim();
  const remove = useRemoveClaimLine();
  const respond = useRecordResponses();
  const resolve = useResolveRejection();
  const [answering, setAnswering] = useState<ClaimLine | null>(null);
  const [resolving, setResolving] = useState<{ line: ClaimLine; resolution: Resolution } | null>(null);
  const [shortfall, setShortfall] = useState<ClaimLine | null>(null);
  const [removing, setRemoving] = useState<ClaimLine | null>(null);
  const [dialog, setDialog] = useState<"submit" | "void" | "close" | "acceptAll" | null>(null);
  const reasons = options.data?.write_off_reasons ?? [];
  const data = claim.data;
  const status = data?.status;
  const answerable = status === "submitted" || status === "responded";

  const actions = (row: ClaimLine): DataTableRowAction[] => {
    const out: DataTableRowAction[] = [];
    if (canRespond && answerable && row.status === "pending")
      out.push({
        label: t("detail.recordAnswer"),
        icon: <MessageSquareReply />,
        onSelect: () => {
          setAnswering(row);
        },
      });
    if (canResolve && status === "responded" && !isZero(row.unresolved_rejection)) {
      out.push({
        label: t("detail.rebill"),
        icon: <UserRoundPlus />,
        onSelect: () => {
          setResolving({ line: row, resolution: "rebilled" });
        },
      });
      out.push({
        label: t("detail.writeOff"),
        icon: <FileX2 />,
        destructive: true,
        onSelect: () => {
          setResolving({ line: row, resolution: "written_off" });
        },
      });
    }
    if (canResolve && status === "responded" && !isZero(row.unpaid))
      out.push({
        label: t("detail.writeOffShortfall"),
        icon: <FileX2 />,
        destructive: true,
        separated: out.length > 0,
        onSelect: () => {
          setShortfall(row);
        },
      });
    if (canManage && status === "draft")
      out.push({
        label: t("detail.removeLine"),
        icon: <Trash2 />,
        destructive: true,
        onSelect: () => {
          setRemoving(row);
        },
      });
    return out;
  };

  const columns = useMemo<ColumnDef<ClaimLine>[]>(
    () => [
      {
        id: "line",
        header: t("detail.columns.line"),
        meta: { label: t("detail.columns.line"), className: "whitespace-normal min-w-56" },
        cell: ({ row }) => <LineIdentity line={row.original} />,
      },
      {
        id: "claimed",
        header: t("detail.columns.claimed"),
        meta: { label: t("detail.columns.claimed"), align: "end" },
        cell: ({ row }) => <MoneyText value={row.original.amount_claimed} currency={false} />,
      },
      {
        id: "answer",
        header: t("detail.columns.answer"),
        meta: { label: t("detail.columns.answer"), className: "whitespace-normal" },
        cell: ({ row }) => <LineAnswer line={row.original} />,
      },
      {
        id: "paid",
        header: t("detail.columns.paid"),
        meta: { label: t("detail.columns.paid"), align: "end" },
        cell: ({ row }) => <MoneyText value={row.original.paid} currency={false} />,
      },
      {
        id: "stage",
        header: t("detail.columns.stage"),
        meta: { label: t("detail.columns.stage") },
        cell: ({ row }) => <ClaimStageBadge stage={row.original.stage} />,
      },
      {
        id: "receivable",
        header: t("detail.columns.receivable"),
        meta: { label: t("detail.columns.receivable"), align: "end" },
        cell: ({ row }) => <MoneyText value={row.original.receivable} currency={false} className="font-semibold" />,
      },
    ],
    [t],
  );

  const pending = (data?.lines ?? []).filter((l) => l.status === "pending");
  const settled = (data?.lines ?? []).every((l) => isZero(l.receivable) && isZero(l.unresolved_rejection));

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader
        title={data ? t("detail.title", { number: data.number }) : t("detail.loadingTitle")}
        description={data ? <ClaimHeaderLine claim={data} /> : null}
        icon={<FileStack />}
        actions={
          <Button asChild variant="outline">
            <Link to="/claims/batches">
              <ArrowBack aria-hidden="true" />
              {t("detail.back")}
            </Link>
          </Button>
        }
      />
      <ClaimsNav />
      {claim.isPending ? (
        <Skeleton className="h-64 w-full" />
      ) : claim.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(claim.error)}
        </AlertCard>
      ) : data ? (
        <>
          <div className="flex flex-wrap items-center gap-2" data-testid="claim-actions">
            {canManage && status === "draft" ? (
              <Button
                onClick={() => {
                  setDialog("submit");
                }}
                data-testid="claim-submit"
              >
                <Send aria-hidden="true" />
                {t("detail.submit")}
              </Button>
            ) : null}
            {canRespond && answerable && pending.length > 0 ? (
              <Button
                variant="secondary"
                onClick={() => {
                  setDialog("acceptAll");
                }}
                data-testid="claim-accept-all"
              >
                <CheckCheck aria-hidden="true" />
                {t("detail.acceptAll", { count: pending.length })}
              </Button>
            ) : null}
            {canManage && status === "responded" ? (
              <Button
                variant={settled ? "default" : "outline"}
                onClick={() => {
                  setDialog("close");
                }}
                data-testid="claim-close"
              >
                <Lock aria-hidden="true" />
                {t("detail.close")}
              </Button>
            ) : null}
            {canManage ? (
              <>
                <Button asChild variant="outline">
                  <a href={exportUrl(claimId, "ar")} download data-testid="claim-export-ar">
                    <FileSpreadsheet aria-hidden="true" />
                    {t("detail.exportAr")}
                  </a>
                </Button>
                <Button asChild variant="outline">
                  <a href={exportUrl(claimId, "en")} download data-testid="claim-export-en">
                    <FileSpreadsheet aria-hidden="true" />
                    {t("detail.exportEn")}
                  </a>
                </Button>
                <Button asChild variant="outline">
                  <Link to="/claims/$claimId/print" params={{ claimId: String(claimId) }} data-testid="claim-print">
                    <Printer aria-hidden="true" />
                    {t("detail.print")}
                  </Link>
                </Button>
              </>
            ) : null}
            {canManage && (status === "draft" || status === "submitted") ? (
              <Button
                variant="destructive-soft"
                onClick={() => {
                  setDialog("void");
                }}
                data-testid="claim-void"
              >
                <Ban aria-hidden="true" />
                {t("detail.void")}
              </Button>
            ) : null}
          </div>
          <AmountTiles
            testId="claim-totals"
            tiles={[
              { key: "claimed", label: t("detail.columns.claimed"), value: data.claimed_total, tone: "primary" },
              { key: "accepted", label: t("detail.accepted"), value: data.accepted_total, tone: "info" },
              { key: "rejected", label: t("detail.rejected"), value: data.rejected_total, tone: "danger" },
              { key: "paid", label: t("detail.columns.paid"), value: data.paid_total, tone: "success" },
              {
                key: "receivable",
                label: t("detail.columns.receivable"),
                value: data.receivable,
                tone: "warning",
                strong: true,
              },
            ]}
          />
          {data.note ? <p className="text-sm text-muted">{data.note}</p> : null}
          <DataTable
            columns={columns}
            data={data.lines}
            getRowId={(r) => String(r.id)}
            caption={t("detail.linesCaption", { number: data.number })}
            rowActions={actions}
            minTableWidth={900}
            pageSize={50}
            emptyState={<EmptyState bare size="compact" icon={<FileStack />} title={t("detail.noLines")} />}
            renderCard={(r, ctx) => (
              <div className="card-surface flex flex-col gap-2 p-4" data-testid="claim-line">
                <div className="flex items-start justify-between gap-2">
                  <LineIdentity line={r} />
                  {ctx.actions}
                </div>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <ClaimStageBadge stage={r.stage} />
                  <MoneyText value={r.amount_claimed} className="text-base" />
                </div>
                <LineAnswer line={r} />
                <dl className="grid grid-cols-2 gap-x-3 text-sm">
                  <div className="flex flex-col">
                    <dt className="text-xs text-muted">{t("detail.columns.paid")}</dt>
                    <dd>
                      <MoneyText value={r.paid} currency={false} />
                    </dd>
                  </div>
                  <div className="flex flex-col">
                    <dt className="text-xs text-muted">{t("detail.columns.receivable")}</dt>
                    <dd>
                      <MoneyText value={r.receivable} currency={false} className="font-semibold" />
                    </dd>
                  </div>
                </dl>
              </div>
            )}
          />
          <section className="card-surface flex flex-col gap-2 p-4 md:p-5" aria-labelledby="claim-payments">
            <h2 id="claim-payments" className="text-base font-semibold">
              {t("detail.payments")}
            </h2>
            {data.payments.length === 0 ? (
              <p className="text-sm text-muted">{t("detail.noPayments")}</p>
            ) : (
              <ul className="flex flex-col divide-y divide-border" data-testid="claim-payments">
                {data.payments.map((p) => (
                  <li key={p.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                    <span className="flex flex-wrap items-center gap-x-3">
                      <bdi className="font-medium">{p.number}</bdi>
                      <DateText value={p.received_on} />
                      <span className="text-muted">{t(`method.${p.method}`)}</span>
                      {p.reversed ? <span className="text-danger-fg">{t("standing.reversed")}</span> : null}
                    </span>
                    <MoneyText value={p.amount} />
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      ) : null}

      <ResponseDialog
        claimId={claimId}
        line={answering}
        onOpenChange={(o) => {
          if (!o) setAnswering(null);
        }}
      />
      <ShortfallDialog
        claimId={claimId}
        line={shortfall}
        reasons={reasons}
        onOpenChange={(o) => {
          if (!o) setShortfall(null);
        }}
      />
      <ReasonDialog
        open={resolving !== null}
        onOpenChange={(o) => {
          if (!o) setResolving(null);
        }}
        title={resolving?.resolution === "rebilled" ? t("resolve.rebillTitle") : t("resolve.writeOffTitle")}
        description={
          resolving?.resolution === "rebilled" ? t("resolve.rebillDescription") : t("resolve.writeOffDescription")
        }
        reasons={reasons.map((r) => ({ code: r.code, label: names.label(r) }))}
        noteRequired={false}
        destructive={resolving?.resolution === "written_off"}
        confirmLabel={resolving?.resolution === "rebilled" ? t("detail.rebill") : t("detail.writeOff")}
        onSubmit={async ({ code, note }) => {
          if (!resolving) return;
          await resolve.mutateAsync({
            claimId,
            lineId: resolving.line.id,
            body: { resolution: resolving.resolution, reason: code, note },
          });
        }}
      >
        {resolving ? (
          <p className="flex flex-wrap items-center justify-between gap-2 rounded-control bg-subtle px-3 py-2 text-sm">
            <span className="min-w-0">
              {names.text(resolving.line.description_ar, resolving.line.description_en)} ·{" "}
              {names.person(resolving.line.patient)}
            </span>
            <MoneyText value={resolving.line.unresolved_rejection} />
          </p>
        ) : null}
      </ReasonDialog>
      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(o) => {
          if (!o) setRemoving(null);
        }}
        title={t("detail.removeTitle")}
        description={t("detail.removeDescription")}
        confirmLabel={t("detail.removeLine")}
        destructive
        onConfirm={async () => {
          if (removing) await remove.mutateAsync({ claimId, lineId: removing.id });
        }}
      />
      <ConfirmDialog
        open={dialog === "submit"}
        onOpenChange={(o) => {
          if (!o) setDialog(null);
        }}
        title={t("detail.submitTitle")}
        description={t("detail.submitDescription")}
        confirmLabel={t("detail.submit")}
        onConfirm={async () => {
          await submit.mutateAsync(claimId);
        }}
      />
      <ConfirmDialog
        open={dialog === "acceptAll"}
        onOpenChange={(o) => {
          if (!o) setDialog(null);
        }}
        title={t("detail.acceptAllTitle")}
        description={t("detail.acceptAllDescription", { count: pending.length })}
        confirmLabel={t("detail.acceptAll", { count: pending.length })}
        onConfirm={async () => {
          await respond.mutateAsync({
            claimId,
            responses: pending.map((l) => ({
              claim_line_id: l.id,
              outcome: "accepted",
              accepted: null,
              reason: "",
              reference: "",
            })),
          });
        }}
      />
      <ConfirmDialog
        open={dialog === "close"}
        onOpenChange={(o) => {
          if (!o) setDialog(null);
        }}
        title={t("detail.closeTitle")}
        description={t("detail.closeDescription")}
        confirmLabel={t("detail.close")}
        onConfirm={async () => {
          await close.mutateAsync(claimId);
        }}
      />
      <NoteDialog
        open={dialog === "void"}
        onOpenChange={(o) => {
          if (!o) setDialog(null);
        }}
        title={t("detail.voidTitle")}
        description={t("detail.voidDescription")}
        label={t("detail.voidReason")}
        confirmLabel={t("detail.void")}
        destructive
        noteRequired
        testId="void-claim-dialog"
        onSubmit={(note) => voidClaim.mutateAsync({ claimId, note })}
      />
    </div>
  );
}

/** Payer, period and status under the claim's title. */
function ClaimHeaderLine({ claim }: { claim: ClaimDetail }) {
  const names = useClaimNames();
  return (
    <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <span>{names.name(claim.payer)}</span>
      <Period start={claim.period_start} end={claim.period_end} />
      <ClaimStatusBadge status={claim.status} />
    </span>
  );
}
