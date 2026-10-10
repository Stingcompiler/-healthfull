import { zodResolver } from "@hookform/resolvers/zod";
import { Lock } from "lucide-react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { z } from "zod";

import { AlertCard } from "@/components/AlertCard";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
  RadioGroupField,
  SwitchField,
  TextField,
} from "@/components/form";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { UnsavedChangesGuard } from "@/components/UnsavedChangesGuard";
import { useTranslateError } from "@/lib/api/translate-error";
import { PERSON_ROLES, ROLES } from "@/lib/auth/permissions";
import { vmsg } from "@/lib/validation";

import { usePolicy, useUpdatePolicy } from "../api";
import { AdminPage, QueryState } from "../components/AdminPage";
import { CheckOption } from "../components/RolesField";
import type { PolicyIn, PolicyOut, RoleCode } from "../types";

const intIn = (min: number, max: number) =>
  z
    .string()
    .trim()
    .regex(/^\d+$/, vmsg("validation.number"))
    .refine((v) => Number(v) >= min && Number(v) <= max, vmsg("admin:policies.range", { min, max }));

const optionalPercent = z
  .string()
  .trim()
  .refine((v) => v === "" || (/^\d+$/.test(v) && Number(v) <= 100), vmsg("admin:policies.range", { min: 0, max: 100 }));

const schema = z.object({
  allow_partial_payment: z.boolean(),
  show_estimated_cost: z.boolean(),
  partial_dispense_remainder: z.enum(["defer", "refund"]),
  pending_transfer_alert_days: intIn(1, 90),
  follow_up_window_days: intIn(0, 365),
  follow_up_discount_percent: z
    .string()
    .trim()
    .regex(/^\d+(\.\d{1,2})?$/, vmsg("validation.number"))
    .refine((v) => Number(v) <= 100, vmsg("admin:policies.range", { min: 0, max: 100 })),
  session_idle_minutes: intIn(5, 1440),
  discount_limit_percent: z.record(z.string(), optionalPercent),
  perform_first_roles: z.array(z.enum(ROLES)),
});
type Values = z.infer<typeof schema>;

function toValues(policy: PolicyOut): Values {
  return {
    allow_partial_payment: policy.allow_partial_payment,
    show_estimated_cost: policy.show_estimated_cost,
    partial_dispense_remainder: policy.partial_dispense_remainder,
    pending_transfer_alert_days: String(policy.pending_transfer_alert_days),
    follow_up_window_days: String(policy.follow_up_window_days),
    follow_up_discount_percent: policy.follow_up_discount_percent,
    session_idle_minutes: String(policy.session_idle_minutes),
    discount_limit_percent: Object.fromEntries(
      PERSON_ROLES.map((r) => [
        r,
        policy.discount_limit_percent[r] === undefined ? "" : String(policy.discount_limit_percent[r]),
      ]),
    ),
    perform_first_roles: policy.perform_first_roles.filter((r): r is RoleCode =>
      (ROLES as readonly string[]).includes(r),
    ),
  };
}

function toBody(values: Values): PolicyIn {
  const limits: Record<string, number> = {};
  for (const [role, value] of Object.entries(values.discount_limit_percent)) {
    if (value.trim() !== "") limits[role] = Number(value);
  }
  return {
    allow_partial_payment: values.allow_partial_payment,
    show_estimated_cost: values.show_estimated_cost,
    partial_dispense_remainder: values.partial_dispense_remainder,
    pending_transfer_alert_days: Number(values.pending_transfer_alert_days),
    follow_up_window_days: Number(values.follow_up_window_days),
    follow_up_discount_percent: values.follow_up_discount_percent,
    session_idle_minutes: Number(values.session_idle_minutes),
    discount_limit_percent: limits,
    perform_first_roles: values.perform_first_roles,
  };
}

export function PoliciesPage() {
  const { t } = useTranslation("admin");
  const policy = usePolicy();
  return (
    <AdminPage section="policies" title={t("sections.policies.title")} description={t("sections.policies.description")}>
      <QueryState loading={policy.isPending} error={policy.error} onRetry={() => void policy.refetch()} rows={6}>
        {policy.data ? <PolicyForm policy={policy.data} /> : null}
      </QueryState>
    </AdminPage>
  );
}

function PolicyForm({ policy }: { policy: PolicyOut }) {
  const { t } = useTranslation(["admin", "common", "errors"]);
  const save = useUpdatePolicy();
  const translateError = useTranslateError();
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: toValues(policy) });
  const submit = form.handleSubmit(async (values) => {
    const saved = await save.mutateAsync(toBody(values));
    form.reset(toValues(saved));
    toast.success(t("admin:policies.saved"));
  });

  return (
    <Form {...form}>
      <UnsavedChangesGuard when={form.formState.isDirty && !form.formState.isSubmitting} />
      <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4">
        {save.error ? (
          <AlertCard variant="danger" title={t("errors:title")} live>
            {translateError(save.error)}
          </AlertCard>
        ) : null}

        <section className="card-surface grid gap-4 p-4 md:p-5" aria-labelledby="pol-billing">
          <h2 id="pol-billing" className="font-semibold text-fg">
            {t("admin:policies.billing")}
          </h2>
          {/* Same row as SwitchField (label first, control at the end, bordered), locked on. */}
          <div className="flex flex-row items-center justify-between gap-4 rounded-control border border-border p-3">
            <div className="grid gap-1">
              <Label htmlFor="pay-first" className="flex items-center gap-1.5">
                {t("admin:policies.payFirst")}
                <Lock className="size-3.5 text-muted" aria-hidden="true" />
              </Label>
              <p id="pay-first-hint" className="text-sm text-muted">
                {t("admin:policies.payFirstHint")}
              </p>
            </div>
            <Switch id="pay-first" checked disabled aria-describedby="pay-first-hint" />
          </div>
          <SwitchField
            control={form.control}
            name="allow_partial_payment"
            label={t("admin:policies.partialPayment")}
            description={t("admin:policies.partialPaymentHint")}
          />
          <div className="grid gap-4 md:grid-cols-2">
            <TextField
              control={form.control}
              name="follow_up_window_days"
              label={t("admin:policies.followUpDays")}
              inputMode="numeric"
              dir="ltr"
            />
            <TextField
              control={form.control}
              name="follow_up_discount_percent"
              label={t("admin:policies.followUpDiscount")}
              inputMode="decimal"
              dir="ltr"
            />
          </div>
          <TextField
            control={form.control}
            name="pending_transfer_alert_days"
            label={t("admin:policies.transferAlertDays")}
            description={t("admin:policies.transferAlertHint")}
            inputMode="numeric"
            dir="ltr"
            className="md:max-w-xs"
          />
        </section>

        <section className="card-surface grid gap-4 p-4 md:p-5" aria-labelledby="pol-discounts">
          <div>
            <h2 id="pol-discounts" className="font-semibold text-fg">
              {t("admin:policies.discountLimits")}
            </h2>
            <p className="text-sm text-muted">{t("admin:policies.discountLimitsHint")}</p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {PERSON_ROLES.map((role) => (
              <FormField
                key={role}
                control={form.control}
                name={`discount_limit_percent.${role}`}
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>{t(`common:roles.${role}`)}</FormLabel>
                    <FormControl>
                      <Input {...field} inputMode="numeric" dir="ltr" placeholder={t("admin:policies.noDiscount")} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            ))}
          </div>
        </section>

        <section className="card-surface grid gap-4 p-4 md:p-5" aria-labelledby="pol-perform">
          <div>
            <h2 id="pol-perform" className="font-semibold text-fg">
              {t("admin:policies.performFirst")}
            </h2>
            <p className="text-sm text-muted">{t("admin:policies.performFirstHint")}</p>
          </div>
          <FormField
            control={form.control}
            name="perform_first_roles"
            render={({ field }) => (
              <FormItem>
                <div role="group" aria-labelledby="pol-perform" className="grid gap-x-4 sm:grid-cols-2 xl:grid-cols-3">
                  {PERSON_ROLES.map((role) => (
                    <CheckOption
                      key={role}
                      id={`pf-${role}`}
                      checked={field.value.includes(role)}
                      onCheckedChange={(checked) => {
                        const next = new Set(field.value);
                        if (checked) next.add(role);
                        else next.delete(role);
                        field.onChange(ROLES.filter((r) => next.has(r)));
                      }}
                      label={t(`common:roles.${role}`)}
                    />
                  ))}
                </div>
                <FormMessage />
              </FormItem>
            )}
          />
        </section>

        <section className="card-surface grid gap-4 p-4 md:p-5" aria-labelledby="pol-ops">
          <h2 id="pol-ops" className="font-semibold text-fg">
            {t("admin:policies.operations")}
          </h2>
          <RadioGroupField
            control={form.control}
            name="partial_dispense_remainder"
            label={t("admin:policies.dispenseRemainder")}
            options={[
              { value: "defer", label: t("admin:policies.remainderDefer") },
              { value: "refund", label: t("admin:policies.remainderRefund") },
            ]}
          />
          <SwitchField
            control={form.control}
            name="show_estimated_cost"
            label={t("admin:policies.estimatedCost")}
            description={t("admin:policies.estimatedCostHint")}
          />
          <TextField
            control={form.control}
            name="session_idle_minutes"
            label={t("admin:policies.sessionIdle")}
            inputMode="numeric"
            dir="ltr"
            className="md:max-w-xs"
          />
        </section>

        <div className="flex gap-2">
          <Button type="submit" loading={form.formState.isSubmitting} disabled={!form.formState.isDirty}>
            {t("admin:common.save")}
          </Button>
          <Button
            type="button"
            variant="outline"
            disabled={!form.formState.isDirty}
            onClick={() => {
              form.reset(toValues(policy));
            }}
          >
            {t("common:actions.reset")}
          </Button>
        </div>
      </form>
    </Form>
  );
}
