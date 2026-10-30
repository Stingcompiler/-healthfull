import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { AlertCard } from "@/components/AlertCard";
import { Form, TextField } from "@/components/form";
import { ArrowBack } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { useTranslateError } from "@/lib/api/translate-error";
import { useDocumentTitle } from "@/lib/hooks/use-document-title";
import { getSiteConfig } from "@/lib/site";
import { vmsg } from "@/lib/validation";

import { portalKeys, portalLogin } from "../api";

/** Arabic-Indic digits typed on a phone keyboard count as digits (the server folds them too). */
const latinDigits = (value: string) =>
  value
    .replace(/[\u0660-\u0669]/g, (d) => String(d.charCodeAt(0) - 0x0660))
    .replace(/[\u06f0-\u06f9]/g, (d) => String(d.charCodeAt(0) - 0x06f0));

const schema = z.object({
  fileNo: z.string().trim().min(1, vmsg("validation.required")),
  // Local (0912345678) or international (+249 912 345 678); the server folds both.
  phone: z
    .string()
    .trim()
    .transform((v) => latinDigits(v).replace(/[\s-]/g, ""))
    .pipe(z.string().regex(/^(?:\+?249|00249|0)?\d{9}$/, vmsg("validation.phone"))),
  code: z
    .string()
    .trim()
    .transform((v) => latinDigits(v).replace(/[\s-]/g, ""))
    .pipe(z.string().regex(/^\d{8}$/, vmsg("portal:login.codeInvalid"))),
});
type Values = z.input<typeof schema>;
type Parsed = z.output<typeof schema>;

/** Patient sign-in with file number, phone and the code printed on a receipt (FEATURES 15.2). */
export function PortalLoginPage() {
  const { t } = useTranslation("portal");
  const translateError = useTranslateError();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const search: { reason?: string } = useSearch({ strict: false });
  useDocumentTitle(t("login.title"));
  const [error, setError] = useState<unknown>(null);
  const form = useForm<Values, unknown, Parsed>({
    resolver: zodResolver(schema),
    defaultValues: { fileNo: "", phone: "", code: "" },
  });

  const onSubmit = form.handleSubmit(async (values) => {
    setError(null);
    try {
      const me = await portalLogin({ file_no: values.fileNo, phone: values.phone, code: values.code });
      queryClient.setQueryData(portalKeys.me, me);
      await navigate({ to: "/portal/home" });
    } catch (caught) {
      setError(caught);
      form.setValue("code", "");
    }
  });

  const notice =
    search.reason === "expired" ? t("login.expired") : search.reason === "signed-out" ? t("login.signedOut") : null;

  return (
    <div className="flex flex-col gap-5">
      <Link
        to="/portal"
        className="-ms-2 inline-flex min-h-11 w-fit items-center gap-1.5 rounded-control px-2 text-sm font-medium text-primary-strong focus-ring"
        data-testid="login-center-link"
      >
        <ArrowBack className="size-4" aria-hidden="true" />
        {t("login.centerLink")}
      </Link>
      <div>
        <h1 className="text-2xl font-bold text-fg">{t("login.title")}</h1>
        <p className="mt-1 text-sm text-pretty text-muted">{t("login.subtitle")}</p>
      </div>

      <div className="grid gap-5 md:grid-cols-[minmax(0,1fr)_minmax(0,18rem)] md:items-start">
        <div className="card-surface grid gap-4 p-(--d-card-pad)">
          {notice && !error ? <AlertCard variant="info" title={notice} live /> : null}
          {error ? <AlertCard variant="danger" title={translateError(error)} live /> : null}
          <Form {...form}>
            <form onSubmit={(e) => void onSubmit(e)} noValidate className="grid gap-4" data-testid="portal-login">
              <TextField
                control={form.control}
                name="fileNo"
                label={t("login.fileNo")}
                description={t("login.fileNoHint")}
                autoComplete="username"
                dir="ltr"
                required
              />
              <TextField
                control={form.control}
                name="phone"
                label={t("login.phone")}
                description={t("login.phoneHint")}
                type="tel"
                inputMode="tel"
                autoComplete="tel"
                dir="ltr"
                required
              />
              <TextField
                control={form.control}
                name="code"
                label={t("login.code")}
                description={t("login.codeHint")}
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={12}
                dir="ltr"
                required
              />
              <Button type="submit" size="lg" className="w-full" loading={form.formState.isSubmitting}>
                {t("login.submit")}
              </Button>
            </form>
          </Form>
        </div>

        <ReceiptGuide />
      </div>
      {getSiteConfig().guestBooking ? (
        <p className="text-sm text-pretty text-muted" data-testid="login-guest-book">
          {t("guest.noFile")}{" "}
          <Link to="/portal/book" className="font-medium text-primary-strong underline-offset-4 hover:underline">
            {t("center.bookOnline")}
          </Link>
        </p>
      ) : null}
    </div>
  );
}

/** Sample values in the receipt outline (shapes only, not anyone's data). */
const SAMPLE_FILE_NO = "PT-2026-000123";
const SAMPLE_CODE = "1234 5678";
const GUIDE_STEPS = ["file", "phone", "code"] as const;

/**
 * Where each detail is printed: a plain outline of the receipt's portal box (not a picture,
 * so it costs nothing on a slow network) and three numbered steps.
 */
function ReceiptGuide() {
  const { t } = useTranslation("portal");
  return (
    <section className="flex flex-col gap-3" aria-labelledby="receipt-guide" data-testid="receipt-guide">
      <h2 id="receipt-guide" className="text-base font-semibold text-fg">
        {t("login.guide.title")}
      </h2>
      <div className="rounded-card border border-dashed border-border-strong bg-surface p-4 text-sm" aria-hidden="true">
        <p className="font-semibold text-fg">{t("code.title")}</p>
        <p className="mt-1 text-muted">
          {t("code.fileNo")}: <bdi className="num text-fg">{SAMPLE_FILE_NO}</bdi>
        </p>
        <p className="mt-2 text-xs text-muted">{t("code.code")}</p>
        <p className="num text-lg font-bold tracking-widest text-fg">{SAMPLE_CODE}</p>
      </div>
      <ol className="flex flex-col gap-2 text-sm text-fg">
        {GUIDE_STEPS.map((step, index) => (
          <li key={step} className="flex gap-2">
            <span className="shrink-0 num font-semibold text-muted">{index + 1}.</span>
            <span className="text-pretty">{t(`login.guide.${step}`)}</span>
          </li>
        ))}
      </ol>
      <p className="text-xs text-pretty text-muted">{t("login.help")}</p>
    </section>
  );
}
