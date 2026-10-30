import { zodResolver } from "@hookform/resolvers/zod";
import { Link } from "@tanstack/react-router";
import { useForm, useWatch } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { z } from "zod";

import { AlertCard } from "@/components/AlertCard";
import { Form, SwitchField, TextareaField, TextField } from "@/components/form";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { UnsavedChangesGuard } from "@/components/UnsavedChangesGuard";
import { useTranslateError } from "@/lib/api/translate-error";
import { vmsg } from "@/lib/validation";

import { usePublicSiteSettings, useUpdatePublicSiteSettings } from "../api";
import { AdminPage, QueryState } from "../components/AdminPage";
import type { PublicSiteSettingsIn, PublicSiteSettingsOut } from "../types";

/** Inclusive ranges of the rules this screen edits; the server checks the same (domain.public_site). */
const RANGES = {
  lead_minutes: [0, 10080],
  horizon_days: [1, 365],
  max_open: [1, 20],
  cancel_cutoff_hours: [0, 168],
  reschedule_cutoff_hours: [0, 168],
  request_ttl_hours: [1, 168],
  min_review_minutes: [0, 1440],
  max_guest_bookings_per_phone: [1, 10],
  max_pending_per_doctor_day: [1, 200],
  max_requests_per_address_day: [1, 1000],
  pow_difficulty_bits: [0, 26],
  guest_retention_days: [1, 3650],
} as const;

type RuleName = keyof typeof RANGES;

const wholeIn = ([min, max]: readonly [number, number]) =>
  z
    .string()
    .trim()
    .regex(/^\d+$/, vmsg("admin:publicSite.range", { min, max }))
    .refine((v) => Number(v) >= min && Number(v) <= max, vmsg("admin:publicSite.range", { min, max }));

const schema = z.object({
  site_enabled: z.boolean(),
  online_booking_enabled: z.boolean(),
  patient_tracking_enabled: z.boolean(),
  lead_minutes: wholeIn(RANGES.lead_minutes),
  horizon_days: wholeIn(RANGES.horizon_days),
  max_open: wholeIn(RANGES.max_open),
  cancel_cutoff_hours: wholeIn(RANGES.cancel_cutoff_hours),
  reschedule_allowed: z.boolean(),
  reschedule_cutoff_hours: wholeIn(RANGES.reschedule_cutoff_hours),
  require_approval: z.boolean(),
  request_ttl_hours: wholeIn(RANGES.request_ttl_hours),
  min_review_minutes: wholeIn(RANGES.min_review_minutes),
  guest_booking_enabled: z.boolean(),
  max_guest_bookings_per_phone: wholeIn(RANGES.max_guest_bookings_per_phone),
  max_pending_per_doctor_day: wholeIn(RANGES.max_pending_per_doctor_day),
  max_requests_per_address_day: wholeIn(RANGES.max_requests_per_address_day),
  pow_difficulty_bits: wholeIn(RANGES.pow_difficulty_bits),
  guest_retention_days: wholeIn(RANGES.guest_retention_days),
  reason: z.string().trim().min(1, vmsg("validation.required")).max(300),
});
type Values = z.infer<typeof schema>;

function toValues(row: PublicSiteSettingsOut): Values {
  return {
    site_enabled: row.site_enabled,
    online_booking_enabled: row.online_booking_enabled,
    patient_tracking_enabled: row.patient_tracking_enabled,
    lead_minutes: String(row.lead_minutes),
    horizon_days: String(row.horizon_days),
    max_open: String(row.max_open),
    cancel_cutoff_hours: String(row.cancel_cutoff_hours),
    reschedule_allowed: row.reschedule_allowed,
    reschedule_cutoff_hours: String(row.reschedule_cutoff_hours),
    require_approval: row.require_approval,
    request_ttl_hours: String(row.request_ttl_hours),
    min_review_minutes: String(row.min_review_minutes),
    guest_booking_enabled: row.guest_booking_enabled,
    max_guest_bookings_per_phone: String(row.max_guest_bookings_per_phone),
    max_pending_per_doctor_day: String(row.max_pending_per_doctor_day),
    max_requests_per_address_day: String(row.max_requests_per_address_day),
    pow_difficulty_bits: String(row.pow_difficulty_bits),
    guest_retention_days: String(row.guest_retention_days),
    reason: "",
  };
}

function toBody(values: Values): PublicSiteSettingsIn {
  return {
    reason: values.reason.trim(),
    site_enabled: values.site_enabled,
    online_booking_enabled: values.online_booking_enabled,
    patient_tracking_enabled: values.patient_tracking_enabled,
    lead_minutes: Number(values.lead_minutes),
    horizon_days: Number(values.horizon_days),
    max_open: Number(values.max_open),
    cancel_cutoff_hours: Number(values.cancel_cutoff_hours),
    reschedule_allowed: values.reschedule_allowed,
    reschedule_cutoff_hours: Number(values.reschedule_cutoff_hours),
    require_approval: values.require_approval,
    request_ttl_hours: Number(values.request_ttl_hours),
    min_review_minutes: Number(values.min_review_minutes),
    guest_booking_enabled: values.guest_booking_enabled,
    max_guest_bookings_per_phone: Number(values.max_guest_bookings_per_phone),
    max_pending_per_doctor_day: Number(values.max_pending_per_doctor_day),
    max_requests_per_address_day: Number(values.max_requests_per_address_day),
    pow_difficulty_bits: Number(values.pow_difficulty_bits),
    guest_retention_days: Number(values.guest_retention_days),
  };
}

/**
 * `/administration/public-site` (ADR 0028, 0029): the three switches that decide what of the
 * center is public, and the online booking rules (environment settings before). Every save
 * carries a reason kept in the audit trail. Requires `core.manage_public_site`.
 */
export function PublicSitePage() {
  const { t } = useTranslation("admin");
  const settings = usePublicSiteSettings();
  return (
    <AdminPage
      section="publicSite"
      title={t("sections.publicSite.title")}
      description={t("sections.publicSite.description")}
    >
      <QueryState loading={settings.isPending} error={settings.error} onRetry={() => void settings.refetch()} rows={5}>
        {settings.data ? <PublicSiteForm row={settings.data} /> : null}
      </QueryState>
    </AdminPage>
  );
}

function LiveSummary({ row }: { row: PublicSiteSettingsOut }) {
  const { t } = useTranslation("admin");
  const live = [
    row.site_enabled ? t("publicSite.liveSite") : null,
    row.online_booking_enabled ? t("publicSite.liveBooking") : null,
    row.patient_tracking_enabled ? t("publicSite.liveTracking") : null,
  ].filter((x): x is string => x !== null);
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="public-site-live">
      <span className="text-sm text-muted">{t("publicSite.liveTitle")}</span>
      {live.length === 0 ? (
        <Badge variant="neutral">{t("publicSite.liveNone")}</Badge>
      ) : (
        live.map((label) => (
          <Badge key={label} variant="success">
            {label}
          </Badge>
        ))
      )}
    </div>
  );
}

function PublicSiteForm({ row }: { row: PublicSiteSettingsOut }) {
  const { t } = useTranslation(["admin", "common", "errors"]);
  const save = useUpdatePublicSiteSettings();
  const translateError = useTranslateError();
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: toValues(row) });
  const submit = form.handleSubmit(async (values) => {
    const saved = await save.mutateAsync(toBody(values));
    form.reset(toValues(saved));
    toast.success(t("admin:publicSite.saved"));
  });
  const rules: { name: RuleName; label: string }[] = [
    { name: "lead_minutes", label: t("admin:publicSite.lead") },
    { name: "horizon_days", label: t("admin:publicSite.horizon") },
    { name: "max_open", label: t("admin:publicSite.maxOpen") },
    { name: "cancel_cutoff_hours", label: t("admin:publicSite.cutoff") },
  ];
  const guestRules: { name: RuleName; label: string; hint: string }[] = [
    {
      name: "max_guest_bookings_per_phone",
      label: t("admin:publicSite.guestPerPhone"),
      hint: t("admin:publicSite.guestPerPhoneHint"),
    },
    {
      name: "max_pending_per_doctor_day",
      label: t("admin:publicSite.pendingPerDoctorDay"),
      hint: t("admin:publicSite.pendingPerDoctorDayHint"),
    },
    {
      name: "max_requests_per_address_day",
      label: t("admin:publicSite.perAddressDay"),
      hint: t("admin:publicSite.perAddressDayHint"),
    },
    { name: "pow_difficulty_bits", label: t("admin:publicSite.powBits"), hint: t("admin:publicSite.powBitsHint") },
    {
      name: "guest_retention_days",
      label: t("admin:publicSite.retentionDays"),
      hint: t("admin:publicSite.retentionDaysHint"),
    },
  ];
  const guestOn = useWatch({ control: form.control, name: "guest_booking_enabled" });
  const rescheduleOn = useWatch({ control: form.control, name: "reschedule_allowed" });
  const approvalOn = useWatch({ control: form.control, name: "require_approval" });

  return (
    <Form {...form}>
      <UnsavedChangesGuard when={form.formState.isDirty && !form.formState.isSubmitting} />
      <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4" data-testid="public-site-form">
        {save.error ? (
          <AlertCard variant="danger" title={t("errors:title")} live>
            {translateError(save.error)}
          </AlertCard>
        ) : null}

        <section className="card-surface grid gap-4 p-4 md:p-(--d-card-pad)" aria-labelledby="ps-switches">
          <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
            <div className="min-w-0">
              <h2 id="ps-switches" className="font-semibold text-fg">
                {t("admin:publicSite.switches")}
              </h2>
              <p className="text-sm text-pretty text-muted">{t("admin:publicSite.switchesHint")}</p>
            </div>
            <LiveSummary row={row} />
          </div>
          <SwitchField
            control={form.control}
            name="site_enabled"
            label={t("admin:publicSite.site")}
            description={t("admin:publicSite.siteHint")}
          />
          <SwitchField
            control={form.control}
            name="online_booking_enabled"
            label={t("admin:publicSite.booking")}
            description={t("admin:publicSite.bookingHint")}
          />
          <SwitchField
            control={form.control}
            name="patient_tracking_enabled"
            label={t("admin:publicSite.tracking")}
            description={t("admin:publicSite.trackingHint")}
          />
          <Button asChild variant="link" className="justify-self-start px-0">
            <Link to="/administration/center-page" data-testid="public-site-edit-content">
              {t("admin:publicSite.editContent")}
            </Link>
          </Button>
          <Button asChild variant="link" className="justify-self-start px-0">
            <Link to="/visits/online-bookings" data-testid="public-site-inbox">
              {t("admin:publicSite.openInbox")}
            </Link>
          </Button>
        </section>

        <section className="card-surface grid gap-4 p-4 md:p-(--d-card-pad)" aria-labelledby="ps-rules">
          <div>
            <h2 id="ps-rules" className="font-semibold text-fg">
              {t("admin:publicSite.rules")}
            </h2>
            <p className="text-sm text-pretty text-muted">{t("admin:publicSite.rulesHint")}</p>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            {rules.map((rule) => (
              <TextField
                key={rule.name}
                control={form.control}
                name={rule.name}
                label={rule.label}
                inputMode="numeric"
                dir="ltr"
              />
            ))}
          </div>
        </section>

        <section className="card-surface grid gap-4 p-4 md:p-(--d-card-pad)" aria-labelledby="ps-approval">
          <div>
            <h2 id="ps-approval" className="font-semibold text-fg">
              {t("admin:publicSite.approvalTitle")}
            </h2>
            <p className="text-sm text-pretty text-muted">{t("admin:publicSite.approvalHint")}</p>
          </div>
          <SwitchField
            control={form.control}
            name="require_approval"
            label={t("admin:publicSite.requireApproval")}
            description={t("admin:publicSite.requireApprovalHint")}
          />
          {approvalOn ? (
            <div className="grid gap-4 sm:grid-cols-2">
              <TextField
                control={form.control}
                name="request_ttl_hours"
                label={t("admin:publicSite.requestTtl")}
                description={t("admin:publicSite.requestTtlHint")}
                inputMode="numeric"
                dir="ltr"
              />
              <TextField
                control={form.control}
                name="min_review_minutes"
                label={t("admin:publicSite.minReview")}
                description={t("admin:publicSite.minReviewHint")}
                inputMode="numeric"
                dir="ltr"
              />
            </div>
          ) : null}
          <SwitchField
            control={form.control}
            name="reschedule_allowed"
            label={t("admin:publicSite.rescheduleAllowed")}
            description={t("admin:publicSite.rescheduleAllowedHint")}
          />
          {rescheduleOn ? (
            <div className="grid gap-4 sm:grid-cols-2">
              <TextField
                control={form.control}
                name="reschedule_cutoff_hours"
                label={t("admin:publicSite.rescheduleCutoff")}
                inputMode="numeric"
                dir="ltr"
              />
            </div>
          ) : null}
        </section>

        <section className="card-surface grid gap-4 p-4 md:p-(--d-card-pad)" aria-labelledby="ps-guest">
          <div>
            <h2 id="ps-guest" className="font-semibold text-fg">
              {t("admin:publicSite.guestTitle")}
            </h2>
            <p className="text-sm text-pretty text-muted">{t("admin:publicSite.guestHint")}</p>
          </div>
          <SwitchField
            control={form.control}
            name="guest_booking_enabled"
            label={t("admin:publicSite.guestBooking")}
            description={t("admin:publicSite.guestBookingHint")}
          />
          {guestOn ? (
            <div className="grid gap-4 sm:grid-cols-2" data-testid="public-site-guest-limits">
              {guestRules.map((rule) => (
                <TextField
                  key={rule.name}
                  control={form.control}
                  name={rule.name}
                  label={rule.label}
                  description={rule.hint}
                  inputMode="numeric"
                  dir="ltr"
                />
              ))}
            </div>
          ) : null}
        </section>

        <section className="card-surface grid gap-4 p-4 md:p-(--d-card-pad)">
          <TextareaField
            control={form.control}
            name="reason"
            label={t("admin:publicSite.reason")}
            description={t("admin:publicSite.reasonHint")}
            rows={2}
          />
        </section>

        <div className="flex flex-wrap gap-2">
          <Button
            type="submit"
            loading={form.formState.isSubmitting}
            disabled={!form.formState.isDirty}
            data-testid="public-site-save"
          >
            {t("admin:publicSite.save")}
          </Button>
          <Button
            type="button"
            variant="outline"
            disabled={!form.formState.isDirty}
            onClick={() => {
              form.reset(toValues(row));
            }}
          >
            {t("common:actions.reset")}
          </Button>
        </div>
      </form>
    </Form>
  );
}
