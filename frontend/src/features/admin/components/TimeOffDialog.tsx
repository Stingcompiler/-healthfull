import { zodResolver } from "@hookform/resolvers/zod";
import { Trash2 } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { z } from "zod";

import { AlertCard } from "@/components/AlertCard";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { TextField } from "@/components/form";
import { Button } from "@/components/ui/button";
import { formatDate } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";
import { vmsg } from "@/lib/validation";

import { useAddTimeOff, useRemoveTimeOff, useTimeOff } from "../api";
import type { DoctorOut } from "../types";
import { QueryState } from "./AdminPage";
import { FormDialog } from "./FormDialog";

const DATE = /^\d{4}-\d{2}-\d{2}$/;
const TIME = /^([01]\d|2[0-3]):[0-5]\d$/;

const schema = z
  .object({
    from_day: z.string().regex(DATE, vmsg("validation.required")),
    from_time: z.string().regex(TIME, vmsg("validation.required")),
    to_day: z.string().regex(DATE, vmsg("validation.required")),
    to_time: z.string().regex(TIME, vmsg("validation.required")),
    reason_ar: z.string().trim().max(200),
    reason_en: z.string().trim().max(200),
  })
  .refine((v) => `${v.to_day}T${v.to_time}` > `${v.from_day}T${v.from_time}`, {
    path: ["to_time"],
    message: vmsg("admin:timeOff.endAfterStart"),
  })
  .refine((v) => v.reason_ar !== "" || v.reason_en !== "", {
    path: ["reason_ar"],
    message: vmsg("admin:timeOff.reasonRequired"),
  });
type Values = z.infer<typeof schema>;

/**
 * A doctor's time off (ADR 0029 C), opened from the doctors' schedule list: no slot inside a
 * period is offered or booked. Bookings already inside it are listed after saving, never
 * cancelled silently. Times are the center's local time.
 */
export function TimeOffDialog({ doctor, onClose }: { doctor: DoctorOut; onClose: () => void }) {
  const { t } = useTranslation("admin");
  const language = useLanguage();
  const list = useTimeOff(doctor.id);
  const add = useAddTimeOff(doctor.id);
  const remove = useRemoveTimeOff(doctor.id);
  const [affected, setAffected] = useState<number>(0);
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { from_day: "", from_time: "08:00", to_day: "", to_time: "17:00", reason_ar: "", reason_en: "" },
  });
  const name = pickName({ ar: doctor.full_name_ar, en: doctor.full_name_en }, language);

  return (
    <FormDialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={t("timeOff.title", { name })}
      description={t("timeOff.hint")}
      form={form}
      error={add.error ?? remove.error}
      wide
      submitLabel={t("timeOff.add")}
      onSubmit={async (v) => {
        const saved = await add.mutateAsync({
          starts_at: `${v.from_day}T${v.from_time}:00`,
          ends_at: `${v.to_day}T${v.to_time}:00`,
          reason_ar: v.reason_ar,
          reason_en: v.reason_en,
        });
        setAffected(saved.appointments.length);
        form.reset({ ...v, reason_ar: "", reason_en: "" });
        toast.success(t("timeOff.added"));
      }}
    >
      <section className="grid gap-2" aria-label={t("timeOff.current")} data-testid="time-off-list">
        <h3 className="text-sm font-semibold text-fg">{t("timeOff.current")}</h3>
        <QueryState loading={list.isPending} error={list.error} onRetry={() => void list.refetch()} rows={2}>
          {list.data && list.data.length > 0 ? (
            <ul className="flex flex-col divide-y divide-border rounded-control border border-border">
              {list.data.map((row) => (
                <li key={row.id} className="flex items-start justify-between gap-3 p-3" data-testid="time-off-row">
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-fg">
                      <bdi className="tabular">{formatDate(row.starts_at, language, "datetime")}</bdi>
                      {" – "}
                      <bdi className="tabular">{formatDate(row.ends_at, language, "datetime")}</bdi>
                    </p>
                    <p className="text-xs break-words text-muted">
                      {pickName({ ar: row.reason_ar, en: row.reason_en }, language)}
                    </p>
                  </div>
                  <ConfirmDialog
                    trigger={
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-sm"
                        aria-label={t("timeOff.remove")}
                        data-testid="time-off-remove"
                      >
                        <Trash2 aria-hidden="true" />
                      </Button>
                    }
                    title={t("timeOff.removeTitle")}
                    description={t("timeOff.removeDescription")}
                    confirmLabel={t("timeOff.remove")}
                    destructive
                    onConfirm={async () => {
                      await remove.mutateAsync(row.id);
                      toast.success(t("timeOff.removed"));
                    }}
                  />
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">{t("timeOff.none")}</p>
          )}
        </QueryState>
      </section>

      {affected > 0 ? (
        <AlertCard variant="warning" title={t("timeOff.affectedTitle", { count: affected })} live>
          {t("timeOff.affectedHint")}
        </AlertCard>
      ) : null}

      <h3 className="text-sm font-semibold text-fg">{t("timeOff.new")}</h3>
      <div className="grid gap-4 sm:grid-cols-2">
        <TextField control={form.control} name="from_day" label={t("timeOff.fromDay")} type="date" dir="ltr" />
        <TextField control={form.control} name="from_time" label={t("timeOff.fromTime")} type="time" dir="ltr" />
        <TextField control={form.control} name="to_day" label={t("timeOff.toDay")} type="date" dir="ltr" />
        <TextField control={form.control} name="to_time" label={t("timeOff.toTime")} type="time" dir="ltr" />
        <TextField control={form.control} name="reason_ar" label={t("timeOff.reasonAr")} dir="rtl" optional />
        <TextField control={form.control} name="reason_en" label={t("timeOff.reasonEn")} dir="ltr" optional />
      </div>
    </FormDialog>
  );
}
