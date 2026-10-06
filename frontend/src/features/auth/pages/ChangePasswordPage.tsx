import { zodResolver } from "@hookform/resolvers/zod";
import { Link, useRouter } from "@tanstack/react-router";
import { KeyRound } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { z } from "zod";

import { AlertCard } from "@/components/AlertCard";
import { Form, PasswordField } from "@/components/form";
import { ArrowBack } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { toApiError, type ApiError } from "@/lib/api/errors";
import { useTranslateError } from "@/lib/api/translate-error";
import { useChangePassword, useCurrentUser } from "@/lib/auth/hooks";
import { vmsg } from "@/lib/validation";

import { AuthLayout } from "../components/AuthLayout";

const PASSWORD_MIN = 8;

const schema = z
  .object({
    oldPassword: z.string().min(1, vmsg("validation.required")),
    newPassword: z
      .string()
      .min(1, vmsg("validation.required"))
      .min(PASSWORD_MIN, vmsg("validation.minLength", { min: PASSWORD_MIN }))
      .refine((v) => !/^\d+$/.test(v), vmsg("validation.passwordNumeric")),
    confirmPassword: z.string().min(1, vmsg("validation.required")),
  })
  .refine((v) => v.newPassword === v.confirmPassword, {
    path: ["confirmPassword"],
    message: vmsg("validation.passwordsMismatch"),
  })
  .refine((v) => v.newPassword !== v.oldPassword, {
    path: ["newPassword"],
    message: vmsg("validation.passwordSameAsOld"),
  });
type Values = z.infer<typeof schema>;

const REASONS = ["old_password_incorrect", "password_unchanged", "password_rejected"] as const;
type Reason = (typeof REASONS)[number];

/** details.reason of a 409 PASSWORD_INVALID (see backend auth_change_password). */
function reasonOf(error: ApiError): Reason | null {
  const reason = error.details.reason;
  return typeof reason === "string" && (REASONS as readonly string[]).includes(reason) ? (reason as Reason) : null;
}

/** Password-policy messages from Django's validators, already in the user's language. */
function serverNotes(error: ApiError): string[] {
  const raw = error.details.messages;
  if (!Array.isArray(raw)) return [];
  return raw.filter((m): m is string => typeof m === "string");
}

export function ChangePasswordPage() {
  const { t } = useTranslation(["auth", "errors"]);
  const router = useRouter();
  const me = useCurrentUser();
  const changePassword = useChangePassword();
  const translateError = useTranslateError();
  const [error, setError] = useState<ApiError | null>(null);
  const forced = me?.must_change_password ?? false;

  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { oldPassword: "", newPassword: "", confirmPassword: "" },
  });

  const onSubmit = form.handleSubmit(async (values) => {
    setError(null);
    try {
      await changePassword.mutateAsync({ old_password: values.oldPassword, new_password: values.newPassword });
      toast.success(t("changePassword.success"));
      form.reset();
      await router.navigate({ to: "/", replace: true });
    } catch (e) {
      const apiError = toApiError(e);
      setError(apiError);
      const reason = apiError.code === "PASSWORD_INVALID" ? reasonOf(apiError) : null;
      if (reason === "old_password_incorrect") {
        form.setError("oldPassword", { message: vmsg(`auth:changePassword.reasons.${reason}`) }, { shouldFocus: true });
      } else if (reason === "password_unchanged") {
        form.setError("newPassword", { message: vmsg(`auth:changePassword.reasons.${reason}`) }, { shouldFocus: true });
      }
    }
  });

  const notes = error ? serverNotes(error) : [];
  const reason = error?.code === "PASSWORD_INVALID" ? reasonOf(error) : null;

  return (
    <AuthLayout>
      <div className="mb-6 text-center">
        <span className="mx-auto mb-4 flex size-12 items-center justify-center rounded-full bg-primary-soft text-primary-strong">
          <KeyRound className="size-6" aria-hidden="true" />
        </span>
        <h1 className="text-2xl font-bold text-fg">{t("changePassword.title")}</h1>
        <p className="mt-1 text-sm text-muted">{t("changePassword.subtitle")}</p>
      </div>

      <div className="card-surface grid gap-4 p-5 md:p-6">
        {forced ? (
          <AlertCard variant="warning" title={t("changePassword.forcedTitle")}>
            {t("changePassword.forcedDescription")}
          </AlertCard>
        ) : null}
        {error ? (
          <AlertCard variant="danger" title={t("errors:title")} live>
            {reason ? t(`changePassword.reasons.${reason}`) : translateError(error)}
            {notes.length > 0 ? (
              <ul className="mt-2 list-disc ps-5">
                {notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            ) : null}
          </AlertCard>
        ) : null}
        <Form {...form}>
          <form onSubmit={(e) => void onSubmit(e)} noValidate className="grid gap-4">
            <PasswordField
              control={form.control}
              name="oldPassword"
              label={t("changePassword.oldPassword")}
              autoComplete="current-password"
              autoFocus
              required
            />
            <PasswordField
              control={form.control}
              name="newPassword"
              label={t("changePassword.newPassword")}
              autoComplete="new-password"
              description={t("changePassword.rules")}
              required
            />
            <PasswordField
              control={form.control}
              name="confirmPassword"
              label={t("changePassword.confirmPassword")}
              autoComplete="new-password"
              required
            />
            <Button type="submit" size="lg" className="mt-1 w-full" loading={form.formState.isSubmitting}>
              {form.formState.isSubmitting ? t("changePassword.submitting") : t("changePassword.submit")}
            </Button>
          </form>
        </Form>
      </div>

      {!forced ? (
        <div className="mt-5 text-center">
          <Button asChild variant="link">
            <Link to="/">
              <ArrowBack />
              {t("changePassword.backToApp")}
            </Link>
          </Button>
        </div>
      ) : null}
    </AuthLayout>
  );
}
