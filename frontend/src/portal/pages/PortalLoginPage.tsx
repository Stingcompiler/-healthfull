import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate, useSearch } from "@tanstack/react-router";
import { CalendarCheck, FlaskConical, ReceiptText, Smartphone } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { AlertCard } from "@/components/AlertCard";
import { Form, TextField } from "@/components/form";
import { Button } from "@/components/ui/button";
import { useTranslateError } from "@/lib/api/translate-error";
import { useDocumentTitle } from "@/lib/hooks/use-document-title";
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
    <div className="flex flex-col gap-6">
      <div className="text-center">
        <span className="mx-auto mb-3 flex size-12 items-center justify-center rounded-full bg-primary-soft text-primary-strong">
          <Smartphone className="size-6" aria-hidden="true" />
        </span>
        <h1 className="text-xl font-bold text-fg">{t("login.title")}</h1>
        <p className="mt-1 text-sm text-pretty text-muted">{t("login.subtitle")}</p>
      </div>

      <div className="card-surface grid gap-4 p-5">
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
        <p className="text-center text-xs text-muted">{t("login.help")}</p>
      </div>

      <section className="grid gap-3">
        <h2 className="text-sm font-semibold text-fg">{t("features.title")}</h2>
        <ul className="grid gap-2">
          {[
            { icon: FlaskConical, text: t("features.results") },
            { icon: CalendarCheck, text: t("features.appointments") },
            { icon: ReceiptText, text: t("features.receipts") },
          ].map(({ icon: Icon, text }) => (
            <li key={text} className="card-surface flex items-center gap-3 p-3">
              <span className="flex size-9 shrink-0 items-center justify-center rounded-control bg-primary-soft text-primary-strong">
                <Icon className="size-[18px]" aria-hidden="true" />
              </span>
              <span className="text-sm text-fg">{text}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
