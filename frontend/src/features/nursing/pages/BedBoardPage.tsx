import { Link } from "@tanstack/react-router";
import { BedDouble, CalendarClock, MoonStar, Plus, Wrench } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";
import { usePermission } from "@/lib/auth/hooks";
import { useLanguage } from "@/lib/i18n-hooks";
import { cn } from "@/lib/utils";

import { useBedBoard, useChargeDue, useSetBedStatus } from "../api";
import { AdmitDialog } from "../components/AdmitDialog";
import { DischargeDialog, TransferDialog, type OccupiedBed } from "../components/BedActionDialogs";
import { NursingTabs } from "../components/NursingTabs";
import { QueryError } from "../components/QueryError";
import { nameOf, patientName } from "../lib";
import type { Bed, BedStatus } from "../types";

const BED_STATUSES: readonly BedStatus[] = ["available", "occupied", "maintenance"];
const NO_WARD_ID = "ward-none";

const STATUS_BADGE: Record<BedStatus, "success" | "info" | "neutral"> = {
  available: "success",
  occupied: "info",
  maintenance: "neutral",
};

/** Wards and beds (FEATURES 10.5): admit, move, discharge, and post the nights due. */
export function BedBoardPage() {
  const { t } = useTranslation("nursing");
  const language = useLanguage();
  const translateError = useTranslateError();
  const board = useBedBoard();
  const charge = useChargeDue();
  const canAdmit = usePermission("visits.admit");
  const canManage = usePermission("visits.manage_beds");
  const [admitBed, setAdmitBed] = useState<number | null | undefined>(undefined);
  const [transfer, setTransfer] = useState<OccupiedBed | null>(null);
  const [discharge, setDischarge] = useState<OccupiedBed | null>(null);
  const data = board.data;
  const freeBeds = useMemo(
    () => (data?.wards ?? []).flatMap((w) => w.beds.filter((b) => b.status === "available")),
    [data],
  );

  const postNights = () => {
    charge.mutate(undefined, {
      onSuccess: (out) => {
        if (out.charged === 0) toast.info(t("beds.nothingDueToast"));
        else toast.success(t("beds.postedToast", { count: out.charged }));
      },
      onError: (e) => toast.error(`${t("beds.postError")}: ${translateError(e)}`),
    });
  };

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title={t("beds.title")}
        description={t("beds.description")}
        icon={<BedDouble />}
        actions={
          <>
            {canManage ? (
              <Button
                variant="outline"
                size="lg"
                className="h-12"
                onClick={postNights}
                loading={charge.isPending}
                data-testid="post-nights"
              >
                <MoonStar aria-hidden="true" />
                {data && data.nights_due > 0
                  ? t("beds.postNightsCount", { count: data.nights_due })
                  : t("beds.postNights")}
              </Button>
            ) : null}
            {canAdmit ? (
              <Button
                size="lg"
                className="h-12"
                onClick={() => {
                  setAdmitBed(null);
                }}
                data-testid="admit-open"
              >
                <Plus aria-hidden="true" />
                {t("beds.admit")}
              </Button>
            ) : null}
          </>
        }
      />
      <NursingTabs current="beds" />

      {board.isError ? (
        <QueryError
          title={t("beds.loadError")}
          error={board.error}
          onRetry={() => void board.refetch()}
          retrying={board.isFetching}
        />
      ) : board.isPending || !data ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" aria-busy="true">
          <Skeleton className="h-40" />
          <Skeleton className="h-40" />
          <Skeleton className="h-40" />
        </div>
      ) : data.wards.length === 0 ? (
        <EmptyState icon={<BedDouble />} title={t("beds.emptyTitle")} description={t("beds.emptyDescription")} />
      ) : (
        <>
          <dl aria-label={t("beds.counts.label")} className="grid grid-cols-3 gap-3">
            {BED_STATUSES.map((s) => (
              <div key={s} className="card-surface flex flex-col gap-1 p-3 md:p-4" data-testid={`bed-count-${s}`}>
                <dt className="text-xs text-muted">{t(`beds.counts.${s}`)}</dt>
                <dd className="tabular text-2xl font-semibold text-fg">{data.counts[s]}</dd>
              </div>
            ))}
          </dl>
          {data.wards.map((ward) => {
            const id = ward.room ? `ward-${String(ward.room.id)}` : NO_WARD_ID;
            return (
              <section key={id} aria-labelledby={id} className="flex flex-col gap-3">
                <h2 id={id} className="text-sm font-semibold text-fg-muted">
                  {ward.room ? nameOf(ward.room, language) : t("beds.noWard")}
                </h2>
                <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                  {ward.beds.map((bed) => (
                    <li key={bed.id} className="min-w-0">
                      <BedCard
                        bed={bed}
                        canAdmit={canAdmit}
                        onAdmit={() => {
                          setAdmitBed(bed.id);
                        }}
                        onTransfer={(o) => {
                          setTransfer(o);
                        }}
                        onDischarge={(o) => {
                          setDischarge(o);
                        }}
                      />
                    </li>
                  ))}
                </ul>
              </section>
            );
          })}
        </>
      )}

      <AdmitDialog
        open={admitBed !== undefined}
        onOpenChange={(open) => {
          if (!open) setAdmitBed(undefined);
        }}
        freeBeds={freeBeds}
        initialBedId={admitBed ?? null}
      />
      <TransferDialog target={transfer} freeBeds={freeBeds} onOpenChange={() => setTransfer(null)} />
      <DischargeDialog target={discharge} onOpenChange={() => setDischarge(null)} />
    </div>
  );
}

function BedCard({
  bed,
  canAdmit,
  onAdmit,
  onTransfer,
  onDischarge,
}: {
  bed: Bed;
  canAdmit: boolean;
  onAdmit: () => void;
  onTransfer: (o: OccupiedBed) => void;
  onDischarge: (o: OccupiedBed) => void;
}) {
  const { t } = useTranslation("nursing");
  const language = useLanguage();
  const translateError = useTranslateError();
  const canManage = usePermission("visits.manage_beds");
  const canDischarge = usePermission("visits.discharge");
  const canChart = usePermission("clinical.view");
  const setStatus = useSetBedStatus();
  const occupant = bed.occupant;

  const toggle = (status: "available" | "maintenance") => {
    setStatus.mutate(
      { bedId: bed.id, status },
      {
        onSuccess: () => toast.success(t("beds.statusToast", { bed: bed.code })),
        onError: (e) => toast.error(`${t("beds.statusError")}: ${translateError(e)}`),
      },
    );
  };

  return (
    <article
      data-testid="bed-card"
      data-bed-code={bed.code}
      data-status={bed.status}
      className={cn(
        "card-surface flex h-full min-w-0 flex-col gap-3 border-s-4 p-4",
        bed.status === "available" && "border-s-success",
        bed.status === "occupied" && "border-s-info",
        bed.status === "maintenance" && "border-s-border-strong",
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-base font-semibold text-fg">
            <bdi>{bed.code}</bdi>
          </h3>
          <p className="text-xs text-pretty break-words text-muted">{nameOf(bed, language)}</p>
        </div>
        <Badge variant={STATUS_BADGE[bed.status]}>
          {bed.status === "maintenance" ? <Wrench aria-hidden="true" /> : null}
          {t(`beds.status.${bed.status}`)}
        </Badge>
      </div>

      {occupant ? (
        <div className="flex min-w-0 flex-col gap-1.5">
          <p className="text-base font-semibold text-pretty break-words text-fg" data-testid="bed-occupant">
            {patientName(occupant.patient, language)}
          </p>
          <p className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
            <bdi className="tabular font-semibold text-fg">{occupant.patient.file_no}</bdi>
            <span>
              <CalendarClock className="me-1 inline size-3.5 align-[-2px]" aria-hidden="true" />
              {t("beds.admittedAt")} <DateText value={occupant.admitted_at} format="date" />
            </span>
          </p>
          <p className="text-xs text-pretty break-words text-muted">
            {t("beds.doctor", { name: nameOf(occupant.admitting_doctor, language) })}
          </p>
          {occupant.diagnosis ? (
            <p className="text-xs text-pretty break-words text-muted">
              {t("beds.diagnosis", { text: occupant.diagnosis })}
            </p>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Badge variant="neutral" data-testid="bed-nights-charged">
              {t("beds.nightsCharged", { count: occupant.nights_charged })}
            </Badge>
            {occupant.nights_due > 0 ? (
              <Badge variant="warning">{t("beds.nightsDue", { count: occupant.nights_due })}</Badge>
            ) : null}
          </div>
        </div>
      ) : null}

      <div className="mt-auto flex flex-wrap justify-end gap-2">
        {occupant ? (
          <>
            {canChart ? (
              <Button variant="ghost" asChild>
                <Link
                  to="/nursing/visits/$visitId"
                  params={{ visitId: String(occupant.visit_id) }}
                  aria-label={t("beds.chartNamed", { name: patientName(occupant.patient, language) })}
                >
                  {t("beds.chart")}
                </Link>
              </Button>
            ) : null}
            {canManage ? (
              <Button
                variant="outline"
                onClick={() => {
                  onTransfer({ bed, occupant });
                }}
                aria-label={t("beds.transferNamed", { name: patientName(occupant.patient, language) })}
                data-testid="bed-transfer"
              >
                {t("beds.transfer")}
              </Button>
            ) : null}
            {canDischarge ? (
              <Button
                variant="outline"
                onClick={() => {
                  onDischarge({ bed, occupant });
                }}
                aria-label={t("beds.dischargeNamed", { name: patientName(occupant.patient, language) })}
                data-testid="bed-discharge"
              >
                {t("beds.discharge")}
              </Button>
            ) : null}
          </>
        ) : bed.status === "available" ? (
          <>
            {canManage ? (
              <Button
                variant="ghost"
                onClick={() => {
                  toggle("maintenance");
                }}
                loading={setStatus.isPending}
                aria-label={t("beds.setMaintenanceNamed", { bed: bed.code })}
              >
                {t("beds.setMaintenance")}
              </Button>
            ) : null}
            {canAdmit ? (
              <Button
                onClick={onAdmit}
                aria-label={t("beds.admitHereNamed", { bed: bed.code })}
                data-testid="bed-admit"
              >
                {t("beds.admitHere")}
              </Button>
            ) : null}
          </>
        ) : canManage ? (
          <Button
            variant="outline"
            onClick={() => {
              toggle("available");
            }}
            loading={setStatus.isPending}
            aria-label={t("beds.setAvailableNamed", { bed: bed.code })}
          >
            {t("beds.setAvailable")}
          </Button>
        ) : null}
      </div>
    </article>
  );
}
