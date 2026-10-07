import { zodResolver } from "@hookform/resolvers/zod";
import { Link, useRouter } from "@tanstack/react-router";
import { ClipboardCheck, LockKeyhole, ShieldCheck, WifiOff } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { safeRedirectTarget } from "@/app/guards";
import { AlertCard } from "@/components/AlertCard";
import { Brand } from "@/components/BrandMark";
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
    <div className="grid min-h-dvh bg-bg lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      {/* Brand panel (desktop) */}
      <aside className="relative hidden overflow-hidden border-e border-border bg-primary-soft lg:flex lg:flex-col lg:justify-between lg:p-10 xl:p-14">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_20%_10%,var(--surface)_0%,transparent_55%),radial-gradient(circle_at_90%_90%,var(--bg)_0%,transparent_50%)] opacity-80"
        />
        <div className="relative">
          <Brand />
        </div>
        <div className="relative max-w-lg">
          {/* Not a heading: this panel precedes the page's h1 in the DOM (WCAG 1.3.1 order). */}
          <p className="text-3xl leading-tight font-bold text-balance text-fg xl:text-4xl">{t("hero.title")}</p>
          <p className="mt-4 text-base text-pretty text-muted">{t("hero.subtitle")}</p>
          <ul className="mt-8 grid gap-4">
            {[
              { icon: WifiOff, text: t("hero.point1") },
              { icon: ClipboardCheck, text: t("hero.point2") },
              { icon: ShieldCheck, text: t("hero.point3") },
            ].map(({ icon: Icon, text }) => (
              <li key={text} className="flex items-start gap-3">
                <span className="flex size-9 shrink-0 items-center justify-center rounded-control bg-surface text-primary-strong shadow-card">
                  <Icon className="size-[18px]" aria-hidden="true" />
                </span>
                <span className="pt-1.5 text-sm font-medium text-fg">{text}</span>
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-xs text-muted">{t("common:appName")}</p>
      </aside>

      {/* Form column */}
      <div className="flex min-w-0 flex-col">
        <header className="flex items-center justify-between gap-3 px-4 py-3 md:px-6">
          <Brand className="lg:invisible" />
          <div className="flex items-center gap-1" aria-label={t("login.preferences")} role="group">
            <LanguageSwitcher />
            <ThemeSwitcher />
          </div>
        </header>

        <main id="main" className="flex flex-1 items-start justify-center px-4 pt-4 pb-12 sm:items-center sm:pt-0">
          <div className="w-full max-w-sm">
            <div className="mb-6 text-center">
              <span className="mx-auto mb-4 flex size-12 items-center justify-center rounded-full bg-primary-soft text-primary-strong">
                <LockKeyhole className="size-6" aria-hidden="true" />
              </span>
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
