import { useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { ShieldCheck } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard, type AlertVariant } from "@/components/AlertCard";
import { BrandMark } from "@/components/BrandMark";
import { DateText } from "@/components/DateText";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { MoneyText } from "@/components/MoneyText";
import { ThemeSwitcher } from "@/components/ThemeSwitcher";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { isApiError } from "@/lib/api/errors";
import { useDocumentTitle } from "@/lib/hooks/use-document-title";

import { useVerifyReceipt } from "../api";
import { Row } from "../components/PortalPage";
import { usePick } from "../lib/ui";

const STATUS_VARIANT: Record<"valid" | "pending" | "void", AlertVariant> = {
  valid: "success",
  pending: "warning",
  void: "danger",
};

/**
 * The public check behind the QR printed on every receipt (FEATURES 15.1): no sign-in, and
 * only what proves the receipt (center, number, day, amount, status, the payer's initials).
 */
export function VerifyPage() {
  const { t } = useTranslation("portal");
  const pick = usePick();
  const navigate = useNavigate();
  const { token } = useParams({ strict: false });
  const search: { r?: string } = useSearch({ strict: false });
  const [typed, setTyped] = useState(search.r ?? "");
  const check = useVerifyReceipt(search.r ?? null, token ?? "");
  useDocumentTitle(t("verify.title"));

  return (
    <div className="flex min-h-dvh flex-col bg-bg">
      <header className="border-b border-border bg-surface">
        <div className="mx-auto flex h-14 w-full max-w-md items-center justify-between gap-2 px-4">
          <span className="flex min-w-0 items-center gap-2">
            <BrandMark className="size-8" />
            <span className="truncate text-sm font-bold text-fg">{t("verify.title")}</span>
          </span>
          <span className="flex items-center">
            <LanguageSwitcher variant="icon" />
            <ThemeSwitcher />
          </span>
        </div>
      </header>
      <main id="main" className="mx-auto flex w-full max-w-md flex-1 flex-col gap-5 px-4 py-6">
        <div className="text-center">
          <span className="mx-auto mb-3 flex size-12 items-center justify-center rounded-full bg-primary-soft text-primary-strong">
            <ShieldCheck className="size-6" aria-hidden="true" />
          </span>
          <h1 className="text-xl font-bold text-fg">{t("verify.title")}</h1>
          <p className="mt-1 text-sm text-pretty text-muted">{t("verify.description")}</p>
        </div>

        {!search.r ? (
          <form
            className="card-surface grid gap-3 p-5"
            onSubmit={(e) => {
              e.preventDefault();
              const value = typed.trim();
              if (value) void navigate({ to: ".", search: { r: value } });
            }}
          >
            <div className="grid gap-1.5">
              <Label htmlFor="verify-number">{t("verify.receiptNumber")}</Label>
              <Input
                id="verify-number"
                value={typed}
                dir="ltr"
                autoCapitalize="characters"
                maxLength={40}
                onChange={(e) => setTyped(e.target.value)}
                aria-describedby="verify-number-hint"
              />
              <p id="verify-number-hint" className="text-xs text-muted">
                {t("verify.receiptHint")}
              </p>
            </div>
            <Button type="submit" size="lg">
              {t("verify.check")}
            </Button>
          </form>
        ) : check.isPending ? (
          <Skeleton className="h-48" />
        ) : check.isError ? (
          <AlertCard
            variant="danger"
            live
            title={
              isApiError(check.error) && check.error.status === 429 ? t("verify.rateLimited") : t("verify.notFound")
            }
          >
            {isApiError(check.error) && check.error.status === 429 ? null : t("verify.notFoundHint")}
          </AlertCard>
        ) : (
          <div className="flex flex-col gap-4" data-testid="verify-result" data-status={check.data.status}>
            <AlertCard variant={STATUS_VARIANT[check.data.status]} title={t(`verify.status.${check.data.status}`)} live>
              {t(`verify.statusHint.${check.data.status}`)}
            </AlertCard>
            <dl className="card-surface divide-y divide-border px-4 py-2">
              <Row label={t("verify.center")}>{pick(check.data.center_name_ar, check.data.center_name_en)}</Row>
              <Row label={t("verify.number")}>
                <bdi data-testid="verify-number">{check.data.receipt_number}</bdi>
              </Row>
              <Row label={t("verify.date")}>
                <DateText value={check.data.date} />
              </Row>
              <Row label={t("verify.amount")}>
                <MoneyText value={check.data.amount} />
              </Row>
              {check.data.patient_initials ? (
                <Row label={t("verify.payer")}>
                  <bdi>{check.data.patient_initials}</bdi>
                </Row>
              ) : null}
            </dl>
          </div>
        )}
      </main>
      <footer className="mx-auto w-full max-w-md px-4 pb-6 safe-bottom text-center text-xs text-muted">
        <p>{t("privacy")}</p>
      </footer>
    </div>
  );
}
