import { zodResolver } from "@hookform/resolvers/zod";
import { Link, useRouter } from "@tanstack/react-router";
import { LockKeyhole } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { safeRedirectTarget } from "@/app/guards";
import { AlertCard } from "@/components/AlertCard";
import { CenterIdentity } from "@/components/CenterIdentity";
import { useCenterPage } from "@/lib/center/api";
import { useTodayText } from "@/lib/center/hooks";
import { pickName } from "@/lib/names";
import { Form, PasswordField, TextField } from "@/components/form";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { ThemeSwitcher } from "@/components/ThemeSwitcher";
import { Button } from "@/components/ui/button";
import { toApiError, type ApiError } from "@/lib/api/errors";
import { useTranslateError } from "@/lib/api/translate-error";
import { useLogin } from "@/lib/auth/hooks";
import { useDocumentTitle } from "@/lib/hooks/use-document-title";
import { formatDate } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";
import { vmsg } from "@/lib/validation";

const loginSchema = z.object({
  username: z.string().trim().min(1, vmsg("validation.required")),
  password: z.string().min(1, vmsg("validation.required")),
});
type LoginValues = z.infer<typeof loginSchema>;

function lockedUntil(error: ApiError): string | null {
  const value = error.details.locked_until ?? error.details.until;
  return typeof value === "string" && !Number.isNaN(Date.parse(value)) ? value : null;
}

/**
 * The side panel of the staff sign-in: the center's identity, today's date and opening
 * status, and today's notices from the center page. Facts only, no product claims. Shown
 * from lg; on phones and tablets the header carries the center's identity.
 */
function CenterPanel() {
  const { t } = useTranslation(["auth", "common"]);
  const language = useLanguage();
  const center = useCenterPage();
  const today = useTodayText(center.data?.today);
  const notices = (center.data?.announcements ?? []).slice(0, 3);
  return (
    <aside
      className="hidden min-w-0 border-e border-border bg-subtle lg:flex lg:flex-col lg:justify-between lg:gap-10 lg:p-10 xl:p-14"
      data-testid="login-center-panel"
    >
      <CenterIdentity size="lg" subtitle={t("panel.staffArea")} nameClassName="text-lg" />
      <div className="flex max-w-md flex-col gap-6">
        <div>
          <p className="text-sm text-muted">{t("panel.today")}</p>
          {/* Not a heading: this panel precedes the page's h1 in the DOM (WCAG 1.3.1 order). */}
          <p className="mt-1 text-2xl font-bold text-balance text-fg" data-testid="login-today">
            {formatDate(new Date(), language, "long")}
          </p>
          {today ? <p className="mt-1 text-sm text-fg">{today}</p> : null}
        </div>
        {notices.length > 0 ? (
          <section aria-labelledby="login-notices" className="card-surface p-4">
            {/* A label, not a heading: the panel comes before the page's h1. */}
            <p id="login-notices" className="text-sm font-semibold text-fg">
              {t("panel.notices")}
            </p>
            <ul className="mt-2 flex flex-col divide-y divide-border">
              {notices.map((n) => {
                const body = pickName({ ar: n.body_ar, en: n.body_en }, language);
                return (
                  <li key={n.id} className="py-2 first:pt-0 last:pb-0">
                    <p className="text-sm font-medium text-fg">
                      {pickName({ ar: n.title_ar, en: n.title_en }, language)}
                    </p>
                    {body ? <p className="mt-0.5 text-sm text-pretty text-muted">{body}</p> : null}
                  </li>
                );
              })}
            </ul>
          </section>
        ) : null}
      </div>
      <p className="text-xs text-muted">{t("common:appName")}</p>
    </aside>
  );
}

export function LoginPage({ redirectTo }: { redirectTo?: string | undefined }) {
  const { t } = useTranslation(["auth", "common"]);
  const router = useRouter();
  const login = useLogin();
  const translateError = useTranslateError();
  const language = useLanguage();
  const [error, setError] = useState<ApiError | null>(null);
  useDocumentTitle(t("login.title"));

  const form = useForm<LoginValues>({
    resolver: zodResolver(loginSchema),
    defaultValues: { username: "", password: "" },
  });

  const onSubmit = form.handleSubmit(async (values) => {
    setError(null);
    try {
      const me = await login.mutateAsync(values);
      const target = me.must_change_password ? "/change-password" : (safeRedirectTarget(redirectTo) ?? "/");
      await router.navigate({ href: target, replace: true });
    } catch (e) {
      const apiError = toApiError(e);
      setError(apiError);
      form.setValue("password", "");
      form.setFocus("password");
    }
  });

  const locked = error?.code === "ACCOUNT_LOCKED";
  const until = error && locked ? lockedUntil(error) : null;

  return (
    <div className="grid min-h-dvh bg-bg lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      {/* Center panel (desktop): who this center is and what staff should know today. */}
      <CenterPanel />

      {/* Form column */}
      <div className="flex min-w-0 flex-col">
        <header className="flex items-center justify-between gap-3 px-4 py-3 md:px-6">
          <CenterIdentity className="lg:invisible" />
          <div className="flex items-center gap-1" aria-label={t("login.preferences")} role="group">
            <LanguageSwitcher />
            <ThemeSwitcher />
          </div>
        </header>

        <main id="main" className="flex flex-1 items-start justify-center px-4 pt-4 pb-12 sm:items-center sm:pt-0">
          <div className="w-full max-w-sm">
            <div className="mb-6 text-center">
              <LockKeyhole className="mx-auto mb-4 size-7 text-primary-strong" aria-hidden="true" />
              <h1 className="text-2xl font-bold text-fg">{t("login.title")}</h1>
              <p className="mt-1 text-sm text-muted">{t("login.subtitle")}</p>
            </div>

            <div className="card-surface p-5 md:p-6">
              <Form {...form}>
                <form
                  onSubmit={(e) => void onSubmit(e)}
                  noValidate
                  className="grid gap-4"
                  aria-label={t("login.title")}
                >
                  {error ? (
                    <AlertCard
                      variant={locked ? "warning" : "danger"}
                      title={locked ? t("login.lockedTitle") : t("login.failedTitle")}
                      live
                    >
                      {translateError(error)}
                      {until ? (
                        <span className="mt-1 block font-medium">
                          {t("login.lockedUntil", { time: formatDate(until, language, "time") })}
                        </span>
                      ) : null}
                    </AlertCard>
                  ) : null}
                  <TextField
                    control={form.control}
                    name="username"
                    label={t("login.username")}
                    autoComplete="username"
                    autoFocus
                    dir="ltr"
                    required
                  />
                  <PasswordField
                    control={form.control}
                    name="password"
                    label={t("login.password")}
                    autoComplete="current-password"
                    required
                  />
                  <Button type="submit" size="lg" className="mt-1 w-full" loading={form.formState.isSubmitting}>
                    {form.formState.isSubmitting ? t("login.submitting") : t("login.submit")}
                  </Button>
                </form>
              </Form>
            </div>

            <p className="mt-5 text-center text-xs text-pretty text-muted">{t("login.forgotHint")}</p>
            <p className="mt-1 text-center text-xs">
              <Link
                to="/portal"
                className="inline-flex min-h-11 items-center px-2 font-medium text-primary-strong underline-offset-4 hover:underline"
              >
                {t("login.portalLink")}
              </Link>
            </p>
          </div>
        </main>
      </div>
    </div>
  );
}
