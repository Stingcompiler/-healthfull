import { Send, XCircle } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { AlertCard } from "@/components/AlertCard";
import { DateText } from "@/components/DateText";
import { ReasonDialog } from "@/components/ReasonDialog";
import { Badge } from "@/components/ui/badge";
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
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useTranslateError } from "@/lib/api/translate-error";
import { useCurrentUser, usePermission } from "@/lib/auth/hooks";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

import { useCancelReferral, useCreateReferral, useReferralTargets } from "../api";
import type { Referral, ReferralInput } from "../types";

type Kind = ReferralInput["kind"];
type Urgency = NonNullable<ReferralInput["urgency"]>;
const URGENCIES: readonly Urgency[] = ["routine", "urgent", "emergency"];

/** Referral notes to another department or an external facility (FEATURES 3.9). */
export function ReferralSection({
  visitId,
  referrals,
  open,
}: {
  visitId: number;
  referrals: readonly Referral[];
  open: boolean;
}) {
  const { t } = useTranslation("clinic");
  const language = useLanguage();
  const me = useCurrentUser();
  const canRefer = usePermission("clinical.refer") && open;
  const [dialogOpen, setDialogOpen] = useState(false);
  const [cancelling, setCancelling] = useState<Referral | null>(null);
  const cancel = useCancelReferral(visitId);

  return (
    <section aria-labelledby="referral-heading" className="card-surface flex flex-col gap-4 p-4 md:p-5">
      <div className="flex flex-wrap items-center gap-2">
        <Send className="size-4 text-muted" aria-hidden="true" />
        <h2 id="referral-heading" className="text-base font-semibold text-fg">
          {t("referral.title")}
        </h2>
        {canRefer ? (
          <Button size="sm" variant="outline" className="ms-auto" onClick={() => setDialogOpen(true)}>
            {t("referral.new")}
          </Button>
        ) : null}
      </div>
      {referrals.length === 0 ? (
        <p className="text-sm text-muted">{t("referral.none")}</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {referrals.map((r) => (
            <li key={r.id} className="flex flex-col gap-1 rounded-control border border-border px-3 py-2 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-fg">
                  {r.kind === "internal"
                    ? r.to_doctor
                      ? pickName({ ar: r.to_doctor.name_ar, en: r.to_doctor.name_en }, language)
                      : r.to_department
                        ? pickName({ ar: r.to_department.name_ar, en: r.to_department.name_en }, language)
                        : ""
                    : r.external_facility}
                </span>
                <Badge variant={r.urgency === "routine" ? "neutral" : "warning"}>
                  {t(`referral.urgency.${r.urgency}`)}
                </Badge>
                <Badge variant={r.status === "issued" ? "info" : "outline"}>{t(`referral.status.${r.status}`)}</Badge>
                <DateText value={r.created_at} className="ms-auto text-xs text-muted" />
              </div>
              <p className="break-words whitespace-pre-line text-fg-muted">{r.reason}</p>
              {r.status === "cancelled" && r.cancel_reason ? (
                <p className="text-xs break-words text-muted">
                  {t("referral.cancelledBecause", { reason: r.cancel_reason })}
                </p>
              ) : null}
              {canRefer && r.status === "issued" && r.referred_by?.id === me?.id ? (
                <div className="flex justify-end">
                  <Button size="sm" variant="ghost" onClick={() => setCancelling(r)}>
                    <XCircle aria-hidden="true" />
                    {t("referral.cancel")}
                  </Button>
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {canRefer ? <ReferralDialog visitId={visitId} open={dialogOpen} onOpenChange={setDialogOpen} /> : null}
      <ReasonDialog
        open={cancelling !== null}
        onOpenChange={(o) => {
          if (!o) setCancelling(null);
        }}
        title={t("referral.cancelTitle")}
        reasons={[]}
        destructive
        confirmLabel={t("referral.cancel")}
        onSubmit={async ({ note }) => {
          if (cancelling) await cancel.mutateAsync({ id: cancelling.id, reason: note });
          toast.success(t("referral.cancelledToast"));
        }}
      />
    </section>
  );
}

function ReferralDialog({
  visitId,
  open,
  onOpenChange,
}: {
  visitId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useTranslation("clinic");
  const { t: tc } = useTranslation();
  const language = useLanguage();
  const targets = useReferralTargets(open);
  const create = useCreateReferral(visitId);
  const translateError = useTranslateError();
  const [kind, setKind] = useState<Kind>("internal");
  const [department, setDepartment] = useState("");
  const [doctor, setDoctor] = useState("");
  const [facility, setFacility] = useState("");
  const [urgency, setUrgency] = useState<Urgency>("routine");
  const [reason, setReason] = useState("");
  const [summary, setSummary] = useState("");
  const [error, setError] = useState<string | null>(null);

  const doctors = (targets.data?.doctors ?? []).filter((d) => !department || String(d.department_id) === department);
  const ready = reason.trim() !== "" && (kind === "internal" ? department !== "" : facility.trim() !== "");

  const reset = () => {
    setKind("internal");
    setDepartment("");
    setDoctor("");
    setFacility("");
    setUrgency("routine");
    setReason("");
    setSummary("");
    setError(null);
  };

  const submit = () => {
    setError(null);
    create.mutate(
      {
        kind,
        reason: reason.trim(),
        to_department_id: kind === "internal" && department ? Number(department) : null,
        to_doctor_id: kind === "internal" && doctor ? Number(doctor) : null,
        external_facility: kind === "external" ? facility.trim() : "",
        clinical_summary: summary.trim(),
        urgency,
      },
      {
        onSuccess: () => {
          toast.success(t("referral.createdToast"));
          reset();
          onOpenChange(false);
        },
        onError: (e) => {
          setError(translateError(e));
        },
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("referral.new")}</DialogTitle>
          <DialogDescription>{t("referral.description")}</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-4">
          <RadioGroup value={kind} onValueChange={(v) => setKind(v as Kind)} className="flex flex-wrap gap-4">
            <label className="flex items-center gap-2 text-sm">
              <RadioGroupItem value="internal" />
              {t("referral.kind.internal")}
            </label>
            <label className="flex items-center gap-2 text-sm">
              <RadioGroupItem value="external" />
              {t("referral.kind.external")}
            </label>
          </RadioGroup>
          {kind === "internal" ? (
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="ref-dept">{t("referral.department")}</Label>
                <Select
                  value={department}
                  onValueChange={(v) => {
                    setDepartment(v);
                    setDoctor("");
                  }}
                >
                  <SelectTrigger id="ref-dept">
                    <SelectValue placeholder={t("referral.choose")} />
                  </SelectTrigger>
                  <SelectContent>
                    {(targets.data?.departments ?? []).map((d) => (
                      <SelectItem key={d.id} value={String(d.id)}>
                        {pickName({ ar: d.name_ar, en: d.name_en }, language)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="ref-doctor">{t("referral.doctor")}</Label>
                <Select value={doctor} onValueChange={setDoctor} disabled={doctors.length === 0}>
                  <SelectTrigger id="ref-doctor">
                    <SelectValue placeholder={t("referral.anyDoctor")} />
                  </SelectTrigger>
                  <SelectContent>
                    {doctors.map((d) => (
                      <SelectItem key={d.id} value={String(d.id)}>
                        {pickName({ ar: d.name_ar, en: d.name_en }, language)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          ) : (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="ref-facility">{t("referral.facility")}</Label>
              <Input id="ref-facility" value={facility} maxLength={200} onChange={(e) => setFacility(e.target.value)} />
            </div>
          )}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="ref-urgency">{t("referral.urgencyLabel")}</Label>
            <Select value={urgency} onValueChange={(v) => setUrgency(v as Urgency)}>
              <SelectTrigger id="ref-urgency">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {URGENCIES.map((u) => (
                  <SelectItem key={u} value={u}>
                    {t(`referral.urgency.${u}`)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="ref-reason">{t("referral.reason")}</Label>
            <Textarea id="ref-reason" value={reason} maxLength={2000} onChange={(e) => setReason(e.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="ref-summary">{t("referral.summary")}</Label>
            <Textarea id="ref-summary" value={summary} maxLength={5000} onChange={(e) => setSummary(e.target.value)} />
          </div>
          {error ? (
            <AlertCard variant="danger" live title={t("referral.saveError")}>
              {error}
            </AlertCard>
          ) : null}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {tc("actions.cancel")}
          </Button>
          <Button onClick={submit} loading={create.isPending} disabled={!ready}>
            <Send aria-hidden="true" />
            {t("referral.issue")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
