import { Link, useParams } from "@tanstack/react-router";
import { CalendarDays, Ellipsis, GitMerge, Pencil, Plus, RotateCcw, UserRound } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { AlertCard } from "@/components/AlertCard";
import { Can } from "@/components/Can";
import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { ArrowNext } from "@/components/icons";
import { PageHeader } from "@/components/PageHeader";
import { PatientCard } from "@/components/PatientCard";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { useUpcomingAppointments } from "@/features/visits/api";
import { CreateVisitDialog } from "@/features/visits/components/CreateVisitDialog";
import { TokenSlipDialog } from "@/features/visits/components/TokenSlipDialog";
import { isApiError } from "@/lib/api/errors";
import { useTranslateError } from "@/lib/api/translate-error";
import { usePermission } from "@/lib/auth/hooks";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";
import { cn } from "@/lib/utils";
import { translateKey } from "@/lib/validation";

import { useMerges, usePatient } from "../api";
import { BalanceCard } from "../components/BalanceCard";
import { CoverageSection } from "../components/CoverageSection";
import { EditPatientDialog } from "../components/EditPatientDialog";
import { MergeDialog } from "../components/MergeDialog";
import { PatientVisits } from "../components/PatientVisits";
import { patientName, toCardPatient } from "../lib";

/** A patient file (FEATURES 1.1-1.6, 2.4): card, coverage, balance, visits with timelines, merge. */
export function PatientProfilePage() {
  const { t } = useTranslation(["patients", "common"]);
  const { t: tAny } = useTranslation();
  const language = useLanguage();
  const { patientId } = useParams({ strict: false });
  const id = Number(patientId);
  const profile = usePatient(id);
  const merges = useMerges(id);
  const canSeeVisits = usePermission("visits.view");
  const canSeeBalance = usePermission("patients.view_balance");
  const canMerge = usePermission("patients.merge");
  const canEdit = usePermission("patients.edit");
  const translateError = useTranslateError();
  const upcoming = useUpcomingAppointments(id, canSeeVisits);
  const [editOpen, setEditOpen] = useState(false);
  const [mergeOpen, setMergeOpen] = useState(false);
  const [visitOpen, setVisitOpen] = useState(false);
  const [tokenEntry, setTokenEntry] = useState<number | null>(null);

  if (profile.isPending) {
    return (
      <div className="flex flex-col gap-6" role="status" aria-label={t("common:loading")}>
        <Skeleton className="h-16" />
        <Skeleton className="h-40" />
      </div>
    );
  }
  if (profile.isError) {
    const notFound = isApiError(profile.error) && profile.error.status === 404;
    const title = notFound ? t("profile.notFoundTitle") : t("profile.loadFailed");
    return (
      <div className="flex flex-col gap-6">
        <PageHeader icon={<UserRound />} title={title} />
        <EmptyState
          icon={<UserRound />}
          title={title}
          description={
            notFound
              ? t("profile.notFoundDescription")
              : `${translateError(profile.error)} ${t("profile.loadFailedDescription")}`
          }
          action={
            <div className="flex flex-wrap justify-center gap-2">
              {notFound ? null : (
                <Button loading={profile.isFetching} onClick={() => void profile.refetch()} data-testid="query-retry">
                  <RotateCcw aria-hidden="true" />
                  {t("common:actions.retry")}
                </Button>
              )}
              <Button asChild variant={notFound ? "default" : "outline"}>
                <Link to="/patients">{t("profile.backToList")}</Link>
              </Button>
            </div>
          }
        />
      </div>
    );
  }

  const { patient, merged_into: mergedInto } = profile.data;
  const hasUpcoming = canSeeVisits && (upcoming.data ?? []).length > 0;
  const cards = 2 + Number(canSeeBalance) + Number(hasUpcoming);
  const active = patient.is_active && !mergedInto;
  const name = patientName(patient, language);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        icon={<UserRound />}
        eyebrow={<Link to="/patients">{t("title")}</Link>}
        // On phones the identity card right below shows the name; the heading stays for readers.
        title={<span className="max-md:sr-only">{name}</span>}
        documentTitle={`${name} · ${patient.file_no}`}
        actions={
          active ? (
            <>
              {canMerge || canEdit ? (
                <>
                  <div className="hidden flex-wrap gap-2 sm:flex">
                    {canMerge ? (
                      <Button
                        variant="outline"
                        onClick={() => {
                          setMergeOpen(true);
                        }}
                      >
                        <GitMerge aria-hidden="true" />
                        {t("merge.open")}
                      </Button>
                    ) : null}
                    {canEdit ? (
                      <Button
                        variant="outline"
                        onClick={() => {
                          setEditOpen(true);
                        }}
                      >
                        <Pencil aria-hidden="true" />
                        {patient.is_incomplete ? t("edit.completeOpen") : t("edit.open")}
                      </Button>
                    ) : null}
                  </div>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button variant="outline" size="icon" className="sm:hidden" aria-label={t("profile.moreActions")}>
                        <Ellipsis aria-hidden="true" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      {canEdit ? (
                        <DropdownMenuItem
                          onSelect={() => {
                            setEditOpen(true);
                          }}
                        >
                          <Pencil />
                          {patient.is_incomplete ? t("edit.completeOpen") : t("edit.open")}
                        </DropdownMenuItem>
                      ) : null}
                      {canMerge ? (
                        <DropdownMenuItem
                          onSelect={() => {
                            setMergeOpen(true);
                          }}
                        >
                          <GitMerge />
                          {t("merge.open")}
                        </DropdownMenuItem>
                      ) : null}
                    </DropdownMenuContent>
                  </DropdownMenu>
                </>
              ) : null}
              <Can permission="visits.create">
                <Button
                  onClick={() => {
                    setVisitOpen(true);
                  }}
                >
                  <Plus aria-hidden="true" />
                  {t("profile.newVisit")}
                </Button>
              </Can>
            </>
          ) : null
        }
      />

      {mergedInto ? (
        <AlertCard
          variant="warning"
          title={t("profile.mergedTitle")}
          action={
            <Button asChild variant="outline" size="sm">
              <Link to="/patients/$patientId" params={{ patientId: String(mergedInto.id) }}>
                {t("profile.openSurvivor")}
              </Link>
            </Button>
          }
        >
          {t("profile.mergedDescription", { fileNo: mergedInto.file_no, name: patientName(mergedInto, language) })}
        </AlertCard>
      ) : null}
      {patient.is_incomplete && active ? (
        <AlertCard variant="warning" title={t("profile.incompleteTitle")}>
          {t("profile.incompleteDescription")}
        </AlertCard>
      ) : null}

      <PatientCard patient={toCardPatient(patient, profile.data, language)} />

      <div className="grid gap-4 lg:grid-cols-2">
        <CoverageSection patientId={id} readOnly={!active} />
        {canSeeBalance ? <BalanceCard patientId={id} /> : null}
        {hasUpcoming ? (
          <section aria-labelledby="upcoming-heading" className="card-surface flex flex-col gap-3 p-4 md:p-5">
            <h2 id="upcoming-heading" className="flex items-center gap-2 text-base font-semibold text-fg">
              <CalendarDays className="size-5 text-muted" aria-hidden="true" />
              {t("profile.upcoming")}
            </h2>
            <ul className="grid gap-2 text-sm">
              {(upcoming.data ?? []).map((a) => (
                <li key={a.id} className="flex flex-wrap justify-between gap-2">
                  <span>{pickName({ ar: a.doctor.name_ar, en: a.doctor.name_en }, language)}</span>
                  <DateText value={a.starts_at} format="datetime" />
                </li>
              ))}
            </ul>
          </section>
        ) : null}
        {/* Details close the grid; alone on its row it takes the full width. */}
        <DetailsCard patient={patient} wide={cards % 2 === 1} />
      </div>

      {canSeeVisits ? (
        <PatientVisits
          patientId={id}
          onNewVisit={
            active
              ? () => {
                  setVisitOpen(true);
                }
              : undefined
          }
        />
      ) : null}

      {(merges.data ?? []).length > 0 ? (
        <section
          aria-labelledby="merges-heading"
          className="card-surface flex flex-col gap-3 p-4 md:p-5"
          data-testid="merge-history"
        >
          <h2 id="merges-heading" className="flex items-center gap-2 text-base font-semibold text-fg">
            <GitMerge className="size-5 text-muted" aria-hidden="true" />
            {t("merge.history")}
          </h2>
          <ul className="grid gap-2 text-sm">
            {(merges.data ?? []).map((m) => (
              <li key={m.id} className="flex flex-col gap-0.5">
                <span>
                  <bdi className="tabular">{m.source.file_no}</bdi>{" "}
                  <ArrowNext className="inline size-3.5" aria-hidden="true" />{" "}
                  <bdi className="tabular">{m.target.file_no}</bdi>
                  {" · "}
                  {m.reason
                    ? pickName({ ar: m.reason.label_ar, en: m.reason.label_en }, language)
                    : m.reason_code
                      ? translateKey(tAny, `patients:merge.reason.${m.reason_code}`)
                      : null}
                  {m.note ? ` · ${m.note}` : null}
                </span>
                <span className="text-xs text-muted">
                  {pickName({ ar: m.merged_by.name_ar, en: m.merged_by.name_en }, language)} ·{" "}
                  <DateText value={m.merged_at} format="datetime" />
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <EditPatientDialog patient={patient} open={editOpen} onOpenChange={setEditOpen} />
      <MergeDialog target={patient} open={mergeOpen} onOpenChange={setMergeOpen} />
      <CreateVisitDialog
        open={visitOpen}
        onOpenChange={setVisitOpen}
        patient={patient}
        onCreated={(visit) => {
          toast.success(t("profile.visitCreated", { number: visit.visit.number }));
          if (visit.queue_entry) setTokenEntry(visit.queue_entry.id);
        }}
      />
      <TokenSlipDialog
        entryId={tokenEntry}
        onOpenChange={(open) => {
          if (!open) setTokenEntry(null);
        }}
      />
    </div>
  );
}

function DetailsCard({
  patient,
  wide,
}: {
  patient: NonNullable<ReturnType<typeof usePatient>["data"]>["patient"];
  wide: boolean;
}) {
  const { t } = useTranslation("patients");
  const rows: [string, string, boolean][] = [
    [t("form.phoneAlt"), patient.phone_alt, true],
    [t("form.nationalId"), patient.national_id, true],
    [t("form.address"), patient.address, false],
    [t("form.emergencyName"), patient.emergency_contact_name, false],
    [t("form.emergencyPhone"), patient.emergency_contact_phone, true],
    [t("form.notes"), patient.notes, false],
  ];
  const shown = rows.filter(([, value]) => value);
  return (
    <section
      aria-labelledby="details-heading"
      className={cn("card-surface flex flex-col gap-3 p-4 md:p-5", wide && "lg:col-span-2")}
    >
      <h2 id="details-heading" className="text-base font-semibold text-fg">
        {t("profile.details")}
      </h2>
      {shown.length === 0 ? (
        <p className="text-sm text-muted">{t("profile.noDetails")}</p>
      ) : (
        <dl className="grid gap-2 text-sm sm:grid-cols-2">
          {shown.map(([label, value, isCode]) => (
            <div key={label} className="min-w-0">
              <dt className="text-muted">{label}</dt>
              <dd className="break-words text-fg">{isCode ? <bdi className="tabular">{value}</bdi> : value}</dd>
            </div>
          ))}
        </dl>
      )}
      <p className="text-xs text-muted">
        {t("profile.registered")} <DateText value={patient.created_at} format="datetime" />
      </p>
    </section>
  );
}
