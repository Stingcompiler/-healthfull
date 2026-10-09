import { BedDouble, UserRound } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { AlertCard } from "@/components/AlertCard";
import { SearchInput } from "@/components/SearchInput";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useTranslateError } from "@/lib/api/translate-error";
import { useLanguage } from "@/lib/i18n-hooks";

import { useAdmit, useOpenVisits, usePatientSearch, useVisitOptions } from "../api";
import { nameOf, patientName } from "../lib";
import type { Bed, PatientRow } from "../types";

const NEW_VISIT = "new";

/** Admit a patient to a free bed (FEATURES 10.5), on an open visit or a new inpatient visit. */
export function AdmitDialog({
  open,
  onOpenChange,
  freeBeds,
  initialBedId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  freeBeds: readonly Bed[];
  initialBedId: number | null;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92dvh] overflow-y-auto sm:max-w-lg">
        {open ? (
          <AdmitForm
            freeBeds={freeBeds}
            initialBedId={initialBedId}
            onDone={() => {
              onOpenChange(false);
            }}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function AdmitForm({
  freeBeds,
  initialBedId,
  onDone,
}: {
  freeBeds: readonly Bed[];
  initialBedId: number | null;
  onDone: () => void;
}) {
  const { t } = useTranslation("nursing");
  const { t: tc } = useTranslation();
  const language = useLanguage();
  const translateError = useTranslateError();
  const [q, setQ] = useState("");
  const [patient, setPatient] = useState<PatientRow | null>(null);
  const [visit, setVisit] = useState(NEW_VISIT);
  const [doctor, setDoctor] = useState("");
  const [bed, setBed] = useState(initialBedId !== null ? String(initialBedId) : "");
  const [diagnosis, setDiagnosis] = useState("");
  const [error, setError] = useState<string | null>(null);
  const search = usePatientSearch(q);
  const visits = useOpenVisits(patient?.id ?? null);
  const options = useVisitOptions(true);
  const admit = useAdmit();
  const openVisits = (visits.data?.items ?? []).filter((v) => v.visit_type !== "pharmacy_sale");
  const ready = patient !== null && doctor !== "" && bed !== "";

  const submit = () => {
    if (!patient) return;
    setError(null);
    admit.mutate(
      {
        patient_id: patient.id,
        visit_id: visit === NEW_VISIT ? null : Number(visit),
        bed_id: Number(bed),
        doctor_id: Number(doctor),
        diagnosis: diagnosis.trim(),
      },
      {
        onSuccess: (adm) => {
          toast.success(t("admit.savedToast", { name: patientName(adm.patient, language), bed: adm.bed?.code ?? "" }));
          onDone();
        },
        onError: (e) => {
          setError(translateError(e));
        },
      },
    );
  };

  return (
    <>
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2">
          <BedDouble className="size-5 text-muted" aria-hidden="true" />
          {t("admit.title")}
        </DialogTitle>
        <DialogDescription>{t("admit.description")}</DialogDescription>
      </DialogHeader>
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (ready) submit();
        }}
      >
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-1.5 text-sm font-medium text-fg">{t("admit.patient")}</legend>
          {patient ? (
            <div className="flex items-center gap-3 rounded-control border border-border px-3 py-2">
              <UserRound className="size-5 shrink-0 text-muted" aria-hidden="true" />
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold text-pretty break-words text-fg" data-testid="admit-patient">
                  {patientName(patient, language)}
                </p>
                <p className="text-xs text-muted">
                  <bdi>{patient.file_no}</bdi>
                </p>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => {
                  setPatient(null);
                  setVisit(NEW_VISIT);
                }}
              >
                {t("admit.change")}
              </Button>
            </div>
          ) : (
            <>
              <SearchInput
                label={t("admit.patientSearch")}
                placeholder={t("admit.patientSearch")}
                onSearch={setQ}
                loading={search.isFetching}
                autoFocus
                data-testid="admit-patient-search"
              />
              {q.trim().length < 2 ? (
                <p className="text-xs text-muted">{t("admit.searchHint")}</p>
              ) : search.data?.items.length === 0 ? (
                <p className="text-sm text-muted">{t("admit.noPatients")}</p>
              ) : (
                <ul className="flex max-h-56 flex-col gap-1 overflow-y-auto">
                  {(search.data?.items ?? []).map((p) => (
                    <li key={p.id}>
                      <button
                        type="button"
                        data-testid="admit-patient-option"
                        data-file-no={p.file_no}
                        onClick={() => {
                          setPatient(p);
                        }}
                        className="flex min-h-12 w-full flex-col items-start rounded-control border border-border px-3 py-2 text-start focus-ring hover:bg-accent"
                      >
                        <span className="text-sm font-medium text-pretty break-words text-fg">
                          {patientName(p, language)}
                        </span>
                        <span className="text-xs text-muted">
                          <bdi>{p.file_no}</bdi>
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </fieldset>

        {patient ? (
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="admit-visit">{t("admit.visit")}</Label>
            <Select value={visit} onValueChange={setVisit}>
              <SelectTrigger id="admit-visit" className="h-12">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NEW_VISIT}>{t("admit.newVisit")}</SelectItem>
                {openVisits.map((v) => (
                  <SelectItem key={v.id} value={String(v.id)}>
                    {t("admit.visitOption", {
                      number: v.number,
                      department: v.department ? nameOf(v.department, language) : "",
                    })}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        ) : null}

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="flex min-w-0 flex-col gap-1.5">
            <Label htmlFor="admit-doctor">{t("admit.doctor")}</Label>
            <Select value={doctor} onValueChange={setDoctor}>
              <SelectTrigger id="admit-doctor" className="h-12" data-testid="admit-doctor">
                <SelectValue placeholder={t("admit.choose")} />
              </SelectTrigger>
              <SelectContent>
                {(options.data?.doctors ?? []).map((d) => (
                  <SelectItem key={d.id} value={String(d.id)}>
                    {nameOf(d, language)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex min-w-0 flex-col gap-1.5">
            <Label htmlFor="admit-bed">{t("admit.bed")}</Label>
            <Select value={bed} onValueChange={setBed} disabled={freeBeds.length === 0}>
              <SelectTrigger id="admit-bed" className="h-12" data-testid="admit-bed">
                <SelectValue placeholder={t("admit.choose")} />
              </SelectTrigger>
              <SelectContent>
                {freeBeds.map((b) => (
                  <SelectItem key={b.id} value={String(b.id)}>
                    {b.code} · {nameOf(b, language)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {freeBeds.length === 0 ? <p className="text-xs text-warning-fg">{t("admit.noFreeBeds")}</p> : null}
          </div>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="admit-diagnosis">{t("admit.diagnosis")}</Label>
          <Input
            id="admit-diagnosis"
            className="h-12"
            value={diagnosis}
            maxLength={300}
            onChange={(e) => {
              setDiagnosis(e.target.value);
            }}
          />
        </div>

        {error ? (
          <AlertCard variant="danger" live title={t("admit.error")}>
            {error}
          </AlertCard>
        ) : null}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onDone}>
            {tc("actions.cancel")}
          </Button>
          <Button type="submit" loading={admit.isPending} disabled={!ready} data-testid="admit-confirm">
            {t("admit.confirm")}
          </Button>
        </DialogFooter>
      </form>
    </>
  );
}
