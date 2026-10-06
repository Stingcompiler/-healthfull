import { zodResolver } from "@hookform/resolvers/zod";
import { CalendarCheck, FlaskConical, ReceiptText, Smartphone } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { AlertCard } from "@/components/AlertCard";
import { Form, TextField } from "@/components/form";
import { Button } from "@/components/ui/button";
import { phoneSchema, vmsg } from "@/lib/validation";

const schema = z.object({
  fileNo: z.string().trim().min(1, vmsg("validation.required")),
  phone: phoneSchema,
  code: z
    .string()
    .trim()
    .regex(/^\d{6}$/, vmsg("portal:login.codeInvalid")),
});
type Values = z.infer<typeof schema>;

/**
 * Placeholder portal sign-in (FEATURES 15.2, Phase 7). The form validates
 * locally; the API does not exist yet, so submitting explains that the
 * portal is being prepared.
 */
export function PortalLoginPage() {
  const { t } = useTranslation("portal");
  const [submitted, setSubmitted] = useState(false);
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { fileNo: "", phone: "", code: "" },
  });

  const onSubmit = form.handleSubmit(() => {
    setSubmitted(true);
  });

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
        {submitted ? (
          <AlertCard variant="info" title={t("login.comingSoonTitle")} live>
            {t("login.comingSoon")}
          </AlertCard>
        ) : null}
        <Form {...form}>
          <form onSubmit={(e) => void onSubmit(e)} noValidate className="grid gap-4">
            <TextField
              control={form.control}
              name="fileNo"
              label={t("login.fileNo")}
              inputMode="numeric"
              dir="ltr"
              required
            />
            <TextField
              control={form.control}
              name="phone"
              label={t("login.phone")}
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
              maxLength={6}
              dir="ltr"
              required
            />
            <Button type="submit" size="lg" className="w-full">
              {t("login.submit")}
            </Button>
          </form>
        </Form>
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
