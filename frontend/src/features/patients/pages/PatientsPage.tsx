import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import type { ColumnDef } from "@tanstack/react-table";
import { FileSpreadsheet, ShieldCheck, Siren, UserPlus, Users } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { Can } from "@/components/Can";
import { DataTable, DataTableOpenButton } from "@/components/DataTable";
import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { SearchInput } from "@/components/SearchInput";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { ageFromBirthDate } from "@/lib/age";
import { formatNumber } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

import { usePatientList } from "../api";
import { EmergencyDialog } from "../components/EmergencyDialog";
import { QueryErrorAlert } from "../components/QueryErrorAlert";
import { patientName } from "../lib";
import type { PatientListItem } from "../types";

/** The server returns at most this many rows; a search narrows the rest. */
const PAGE_SIZE = 100;

/** Patient files: search by name, phone or file number (FEATURES 0.9, 1.1). */
export function PatientsPage() {
  const { t } = useTranslation(["patients", "common"]);
  const language = useLanguage();
  const navigate = useNavigate();
  const search: { q?: string } = useSearch({ strict: false });
  const [term, setTerm] = useState(search.q ?? "");
  const [incomplete, setIncomplete] = useState(false);
  const [emergencyOpen, setEmergencyOpen] = useState(false);
  const list = usePatientList({ q: term, page: 1, pageSize: PAGE_SIZE, incomplete });
  const rows = list.data?.items ?? [];
  const total = list.data?.count ?? 0;

  const ageText = (p: PatientListItem): string => {
    if (!p.date_of_birth) return "";
    const age = ageFromBirthDate(p.date_of_birth);
    if (!age) return "";
    return age.years >= 1
      ? t("common:patient.years", { count: age.years })
      : t("common:patient.months", { count: age.months });
  };

  const open = (p: PatientListItem) => {
    void navigate({ to: "/patients/$patientId", params: { patientId: String(p.id) } });
  };

  const columns = useMemo<ColumnDef<PatientListItem>[]>(
    () => [
      {
        id: "name",
        header: t("list.name"),
        meta: { label: t("list.name") },
        accessorFn: (p) => patientName(p, language),
        cell: ({ row }) => <span className="font-medium break-words">{patientName(row.original, language)}</span>,
      },
      {
        id: "file_no",
        header: t("list.fileNo"),
        meta: { label: t("list.fileNo") },
        accessorKey: "file_no",
        cell: ({ row }) => <bdi className="tabular">{row.original.file_no}</bdi>,
      },
      {
        id: "sex_age",
        header: t("list.sexAge"),
        meta: { label: t("list.sexAge") },
        enableSorting: false,
        cell: ({ row }) => (
          <span className="text-muted">
            {[t(`common:sex.${row.original.sex}`), ageText(row.original)].filter(Boolean).join(" · ")}
          </span>
        ),
      },
      {
        id: "phone",
        header: t("list.phone"),
        meta: { label: t("list.phone") },
        accessorKey: "phone",
        enableSorting: false,
        cell: ({ row }) => <bdi className="tabular">{row.original.phone}</bdi>,
      },
      {
        id: "coverage",
        header: t("list.coverage"),
        meta: { label: t("list.coverage") },
        enableSorting: false,
        cell: ({ row }) => <CoverageBadge patient={row.original} />,
      },
      {
        id: "created_at",
        header: t("list.registered"),
        meta: { label: t("list.registered") },
        accessorKey: "created_at",
        cell: ({ row }) => <DateText value={row.original.created_at} />,
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps -- ageText only reads t
    [t, language],
  );

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        icon={<Users />}
        title={t("title")}
        description={t("description")}
        actions={
          <>
            <Can permission="patients.register_emergency">
              <Button
                variant="destructive-soft"
                onClick={() => {
                  setEmergencyOpen(true);
                }}
              >
                <Siren aria-hidden="true" />
                {t("emergency.open")}
              </Button>
            </Can>
            <Can permission="imports.run">
              <Button asChild variant="outline">
                <Link to="/patients/import">
                  <FileSpreadsheet aria-hidden="true" />
                  {t("import.open")}
                </Link>
              </Button>
            </Can>
            <Can permission="patients.create">
              <Button asChild>
                <Link to="/patients/new">
                  <UserPlus aria-hidden="true" />
                  {t("new.open")}
                </Link>
              </Button>
            </Can>
          </>
        }
      />

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <SearchInput
          label={t("list.searchLabel")}
          placeholder={t("list.searchPlaceholder")}
          defaultValue={search.q ?? ""}
          onSearch={setTerm}
          loading={list.isFetching}
          className="sm:max-w-md"
          autoFocus
        />
        <label className="flex items-center gap-2 text-sm text-fg">
          <Switch checked={incomplete} onCheckedChange={setIncomplete} />
          {t("list.incompleteOnly")}
        </label>
      </div>

      {list.isError ? (
        <QueryErrorAlert
          title={t("list.loadFailed")}
          error={list.error}
          onRetry={() => void list.refetch()}
          retrying={list.isFetching}
        />
      ) : null}

      {total > rows.length ? (
        <p className="text-sm text-muted" role="status">
          {t("list.truncated", { count: rows.length, total: formatNumber(total, language) })}
        </p>
      ) : null}

      {list.isError ? null : (
        <DataTable
          caption={t("list.caption")}
          columns={columns}
          data={rows}
          loading={list.isPending}
          getRowId={(p) => String(p.id)}
          onRowClick={open}
          rowLabel={(p) => t("list.openFile", { name: patientName(p, language) })}
          pageSize={25}
          minTableWidth={760}
          renderCard={(p, { open: openCard, openLabel }) => (
            <div className="card-surface relative flex flex-col gap-2 p-4">
              {openCard ? (
                <DataTableOpenButton onOpen={openCard} label={openLabel}>
                  <span className="font-semibold break-words text-fg">{patientName(p, language)}</span>
                </DataTableOpenButton>
              ) : null}
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
                <bdi className="tabular font-semibold text-fg">{p.file_no}</bdi>
                <span>{[t(`common:sex.${p.sex}`), ageText(p)].filter(Boolean).join(" · ")}</span>
                {p.phone ? <bdi className="tabular">{p.phone}</bdi> : null}
              </div>
              <div className="flex flex-wrap gap-1.5">
                <CoverageBadge patient={p} />
              </div>
            </div>
          )}
          emptyState={
            <EmptyState
              icon={<Users />}
              title={term ? t("list.noMatchTitle") : t("list.emptyTitle")}
              description={term ? t("list.noMatchDescription") : t("list.emptyDescription")}
              action={
                <Can permission="patients.create">
                  <Button asChild>
                    <Link to="/patients/new">{t("new.open")}</Link>
                  </Button>
                </Can>
              }
            />
          }
        />
      )}
      <EmergencyDialog open={emergencyOpen} onOpenChange={setEmergencyOpen} />
    </div>
  );
}

function CoverageBadge({ patient }: { patient: PatientListItem }) {
  const { t } = useTranslation(["patients", "common"]);
  const language = useLanguage();
  return (
    <span className="inline-flex flex-wrap gap-1.5">
      <Badge variant={patient.coverage ? "info" : "outline"}>
        <ShieldCheck aria-hidden="true" />
        {patient.coverage
          ? pickName({ ar: patient.coverage.payer_name_ar, en: patient.coverage.payer_name_en }, language)
          : t("common:patient.cash")}
      </Badge>
      {patient.is_incomplete ? <Badge variant="warning">{t("badges.incomplete")}</Badge> : null}
    </span>
  );
}
