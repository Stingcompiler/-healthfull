import { Link } from "@tanstack/react-router";
import { Ban, PackageCheck, Printer, Syringe, TestTube } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { DateText } from "@/components/DateText";
import { ReasonDialog } from "@/components/ReasonDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { useTranslateError } from "@/lib/api/translate-error";
import { usePermission } from "@/lib/auth/hooks";

import { useCollectSample, useLabReasons, useReceiveSample, useRejectSample } from "../api";
import { useLabNames } from "../lib/use-lab-names";
import type { LabResult } from "../types";

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0 text-end">{children}</dd>
    </div>
  );
}

/**
 * The sample of a test (FEATURES 9.2): receive it in the lab (one tube may serve other tests
 * of the visit), print its label, or reject an unusable one with a reason.
 */
export function SamplePanel({ result }: { result: LabResult }) {
  const { t } = useTranslation(["lab", "common", "errors"]);
  const names = useLabNames();
  const canReceive = usePermission("lab.receive_sample");
  const canLabel = usePermission("lab.collect_sample");
  const [receiving, setReceiving] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const receive = useReceiveSample(result.line.id);
  const reject = useRejectSample(result.line.id);
  const reasons = useLabReasons("sample_reject", rejecting);
  const translateError = useTranslateError();
  const sample = result.sample;
  const usable = sample !== null && sample.status !== "rejected";
  const open = result.stage !== "done" && result.stage !== "cancelled";
  const hasApproved = result.versions.some((v) => v.status !== "draft");

  return (
    <section className="card-surface flex min-w-0 flex-col gap-3 p-4 md:p-5" data-testid="sample-panel">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-base font-semibold">
          <TestTube className="size-4 text-muted" aria-hidden="true" />
          {t("sample.title")}
        </h2>
        {sample ? (
          <Badge variant={sample.status === "rejected" ? "danger" : sample.status === "received" ? "success" : "info"}>
            {t(`sampleStatus.${sample.status}`)}
          </Badge>
        ) : null}
      </div>
      <dl className="grid gap-1 text-sm">
        <Row label={t("sample.type")}>
          {t(`sampleType.${result.test.sample_type}`)}
          {result.test.container ? <span className="text-muted"> · {result.test.container}</span> : null}
        </Row>
        {sample ? (
          <>
            <Row label={t("sample.accession")}>
              <bdi className="font-semibold" data-testid="accession-no">
                {sample.accession_no}
              </bdi>
            </Row>
            <Row label={t("sample.collected")}>
              <DateText value={sample.collected_at} format="datetime" /> · {names.user(sample.collected_by)}
            </Row>
            {sample.received_at ? (
              <Row label={t("sample.received")}>
                <DateText value={sample.received_at} format="datetime" /> · {names.user(sample.received_by)}
              </Row>
            ) : null}
          </>
        ) : null}
      </dl>
      {sample?.status === "rejected" ? (
        <AlertCard variant="warning" title={t("sample.rejectedTitle")}>
          {names.reason(sample.rejection_reason)}
          {sample.rejection_note ? ` · ${sample.rejection_note}` : ""}
        </AlertCard>
      ) : null}
      {receive.isError ? (
        <AlertCard variant="danger" title={t("errors:title")} live>
          {translateError(receive.error)}
        </AlertCard>
      ) : null}
      {open ? (
        <div className="flex flex-wrap gap-2">
          {canReceive && (sample === null || sample.status === "rejected") ? (
            <Button
              onClick={() => {
                setReceiving(true);
              }}
              data-testid="receive-sample"
            >
              <Syringe aria-hidden="true" />
              {sample ? t("sample.newSample") : t("sample.receive")}
            </Button>
          ) : null}
          {canReceive && sample?.status === "collected" ? (
            <Button
              loading={receive.isPending}
              onClick={() => {
                receive.mutate(sample.id);
              }}
              data-testid="receive-collected"
            >
              <PackageCheck aria-hidden="true" />
              {t("sample.receiveCollected")}
            </Button>
          ) : null}
          {canLabel && usable ? (
            <Button asChild variant="outline">
              <Link
                to="/lab/samples/$sampleId/label"
                params={{ sampleId: String(sample.id) }}
                search={{ line: result.line.id }}
                data-testid="print-label"
              >
                <Printer aria-hidden="true" />
                {t("sample.printLabel")}
              </Link>
            </Button>
          ) : null}
          {canReceive && usable && !hasApproved ? (
            <Button
              variant="destructive-soft"
              onClick={() => {
                setRejecting(true);
              }}
              data-testid="reject-sample"
            >
              <Ban aria-hidden="true" />
              {t("sample.reject")}
            </Button>
          ) : null}
        </div>
      ) : null}
      {receiving ? (
        <ReceiveDialog
          result={result}
          onClose={() => {
            setReceiving(false);
          }}
        />
      ) : null}
      <ReasonDialog
        open={rejecting}
        onOpenChange={setRejecting}
        title={t("sample.rejectTitle", { accession: sample?.accession_no ?? "" })}
        description={t("sample.rejectDescription")}
        reasons={(reasons.data ?? []).map((r) => ({ code: r.code, label: names.reason(r) }))}
        noteRequired={false}
        destructive
        confirmLabel={t("sample.reject")}
        onSubmit={async ({ code, note }) => {
          if (!sample) return;
          await reject.mutateAsync({ sampleId: sample.id, reason: code, note });
        }}
      />
    </section>
  );
}

/** Collect and receive one tube for this test and, when chosen, other tests of the visit. */
function ReceiveDialog({ result, onClose }: { result: LabResult; onClose: () => void }) {
  const { t } = useTranslation(["lab", "common", "errors"]);
  const names = useLabNames();
  const translateError = useTranslateError();
  const collect = useCollectSample(result.line.id);
  const [chosen, setChosen] = useState<number[]>(result.companions.map((c) => c.line_id));

  return (
    <Dialog
      open
      onOpenChange={(o) => {
        if (!o && !collect.isPending) onClose();
      }}
    >
      <DialogContent data-testid="receive-dialog">
        <DialogHeader>
          <DialogTitle>{t("sample.receiveTitle")}</DialogTitle>
          <DialogDescription>
            {t("sample.receiveDescription", { type: t(`sampleType.${result.test.sample_type}`) })}
          </DialogDescription>
        </DialogHeader>
        <ul className="grid gap-2 text-sm">
          <li className="flex items-center gap-2 rounded-control bg-subtle px-3 py-2">
            <Checkbox checked disabled aria-label={names.test(result.test)} />
            <span className="font-medium">{names.test(result.test)}</span>
            <bdi className="ms-auto text-xs text-muted">{result.test.code}</bdi>
          </li>
          {result.companions.map((c) => {
            const id = `companion-${String(c.line_id)}`;
            return (
              <li key={c.line_id} className="flex items-center gap-2 rounded-control border border-border px-3 py-2">
                <Checkbox
                  id={id}
                  checked={chosen.includes(c.line_id)}
                  onCheckedChange={(v) => {
                    setChosen((prev) => (v === true ? [...prev, c.line_id] : prev.filter((x) => x !== c.line_id)));
                  }}
                />
                <Label htmlFor={id} className="font-normal">
                  {names.test(c.test)}
                </Label>
                <bdi className="ms-auto text-xs text-muted">{c.test.code}</bdi>
              </li>
            );
          })}
        </ul>
        {result.companions.length > 0 ? <p className="text-xs text-muted">{t("sample.companionsHint")}</p> : null}
        {collect.isError ? (
          <AlertCard variant="danger" title={t("errors:title")} live>
            {translateError(collect.error)}
          </AlertCard>
        ) : null}
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={collect.isPending}>
            {t("common:actions.cancel")}
          </Button>
          <Button
            loading={collect.isPending}
            data-testid="confirm-receive"
            onClick={() => {
              collect.mutate(
                { lineIds: [result.line.id, ...chosen], receive: true },
                {
                  onSuccess: onClose,
                },
              );
            }}
          >
            <PackageCheck aria-hidden="true" />
            {t("sample.confirmReceive")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
