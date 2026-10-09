import { ClipboardCheck, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { AlertCard } from "@/components/AlertCard";
import { ReasonDialog } from "@/components/ReasonDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useTranslateError } from "@/lib/api/translate-error";
import { useCurrentUser, usePermission } from "@/lib/auth/hooks";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

import { useCreateDiagnosis, useDeleteDiagnosis } from "../api";
import type { Diagnosis, DiagnosisInput, Icd10 } from "../types";
import { Icd10Picker } from "./Icd10Picker";

type Kind = DiagnosisInput["kind"];
type Certainty = DiagnosisInput["certainty"];

/** Diagnoses of the visit: ICD-10 lookup, free text, or both (FEATURES 3.3). */
export function DiagnosisSection({
  visitId,
  diagnoses,
  open,
}: {
  visitId: number;
  diagnoses: readonly Diagnosis[];
  open: boolean;
}) {
  const { t } = useTranslation("clinic");
  const language = useLanguage();
  const me = useCurrentUser();
  const canRecord = usePermission("clinical.record_diagnosis") && open;
  const create = useCreateDiagnosis(visitId);
  const remove = useDeleteDiagnosis(visitId);
  const translateError = useTranslateError();
  const [code, setCode] = useState<Icd10 | null>(null);
  const [text, setText] = useState("");
  const [kind, setKind] = useState<Kind>(diagnoses.length === 0 ? "primary" : "secondary");
  const [certainty, setCertainty] = useState<Certainty>("provisional");
  const [error, setError] = useState<string | null>(null);
  const [removing, setRemoving] = useState<Diagnosis | null>(null);

  const add = () => {
    setError(null);
    create.mutate(
      { icd10_code: code?.code ?? null, text: text.trim(), kind, certainty },
      {
        onSuccess: () => {
          setCode(null);
          setText("");
          setKind("secondary");
          toast.success(t("diagnosis.addedToast"));
        },
        onError: (e) => {
          setError(translateError(e));
        },
      },
    );
  };

  return (
    <section aria-labelledby="dx-heading" className="card-surface flex flex-col gap-4 p-4 md:p-5">
      <div className="flex items-center gap-2">
        <ClipboardCheck className="size-4 text-muted" aria-hidden="true" />
        <h2 id="dx-heading" className="text-base font-semibold text-fg">
          {t("diagnosis.title")}
        </h2>
      </div>

      {diagnoses.length > 0 ? (
        <ul className="flex flex-col gap-2" data-testid="diagnosis-list">
          {diagnoses.map((d) => (
            <li
              key={d.id}
              className="flex min-w-0 flex-wrap items-center gap-2 rounded-control border border-border px-3 py-2 text-sm"
            >
              {d.icd10 ? <bdi className="tabular font-semibold">{d.icd10.code}</bdi> : null}
              <span className="min-w-0 flex-1 break-words text-fg">
                {d.icd10 ? pickName({ ar: d.icd10.title_ar, en: d.icd10.title_en }, language) : null}
                {d.icd10 && d.text ? " · " : null}
                {d.text}
              </span>
              <Badge variant={d.kind === "primary" ? "soft" : "neutral"}>{t(`diagnosis.kind.${d.kind}`)}</Badge>
              <Badge variant={d.certainty === "confirmed" ? "success" : "outline"}>
                {t(`diagnosis.certainty.${d.certainty}`)}
              </Badge>
              {canRecord && d.recorded_by?.id === me?.id ? (
                <Button
                  size="icon-sm"
                  variant="ghost"
                  aria-label={t("diagnosis.removeNamed", { name: d.icd10?.code ?? d.text })}
                  title={t("diagnosis.remove")}
                  onClick={() => setRemoving(d)}
                >
                  <Trash2 aria-hidden="true" />
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted">{t("diagnosis.none")}</p>
      )}

      <ReasonDialog
        open={removing !== null}
        onOpenChange={(o) => {
          if (!o) setRemoving(null);
        }}
        title={t("diagnosis.removeTitle")}
        reasons={[]}
        destructive
        confirmLabel={t("diagnosis.remove")}
        onSubmit={async ({ note }) => {
          if (removing) await remove.mutateAsync({ id: removing.id, reason: note });
          toast.success(t("diagnosis.removedToast"));
        }}
      >
        {removing ? (
          <p className="rounded-control bg-subtle px-3 py-2 text-sm break-words text-fg">
            {removing.icd10 ? <bdi className="tabular font-semibold">{removing.icd10.code}</bdi> : null}
            {removing.icd10 ? " " : null}
            {removing.icd10 ? pickName({ ar: removing.icd10.title_ar, en: removing.icd10.title_en }, language) : null}
            {removing.icd10 && removing.text ? " · " : null}
            {removing.text}
          </p>
        ) : null}
      </ReasonDialog>

      {canRecord ? (
        <div className="flex flex-col gap-3 rounded-control bg-subtle p-3" data-testid="diagnosis-form">
          <Icd10Picker value={code} onChange={setCode} label={t("diagnosis.icd10")} />
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5 sm:col-span-2">
              <Label htmlFor="dx-text">{t("diagnosis.text")}</Label>
              <Input
                id="dx-text"
                value={text}
                maxLength={300}
                onChange={(e) => {
                  setText(e.target.value);
                }}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="dx-kind">{t("diagnosis.kindLabel")}</Label>
              <Select value={kind} onValueChange={(v) => setKind(v as Kind)}>
                <SelectTrigger id="dx-kind">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="primary">{t("diagnosis.kind.primary")}</SelectItem>
                  <SelectItem value="secondary">{t("diagnosis.kind.secondary")}</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="dx-certainty">{t("diagnosis.certaintyLabel")}</Label>
              <Select value={certainty} onValueChange={(v) => setCertainty(v as Certainty)}>
                <SelectTrigger id="dx-certainty">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="provisional">{t("diagnosis.certainty.provisional")}</SelectItem>
                  <SelectItem value="confirmed">{t("diagnosis.certainty.confirmed")}</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          {error ? (
            <AlertCard variant="danger" live title={t("diagnosis.addError")}>
              {error}
            </AlertCard>
          ) : null}
          <div className="flex justify-end">
            <Button
              onClick={add}
              loading={create.isPending}
              disabled={!code && !text.trim()}
              data-testid="diagnosis-add"
            >
              <Plus aria-hidden="true" />
              {t("diagnosis.add")}
            </Button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
