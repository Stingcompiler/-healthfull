import { zodResolver } from "@hookform/resolvers/zod";
import { useParams } from "@tanstack/react-router";
import { ClipboardCheck, Printer } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { AlertCard } from "@/components/AlertCard";
import { Form, RadioGroupField, TextareaField } from "@/components/form";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";
import { usePermission } from "@/lib/auth/hooks";
import { vmsg } from "@/lib/validation";

import { useReviewShift, useShift } from "../api";
import { CashierNav } from "../components/CashierNav";
import { PrintArea } from "../components/PrintFrame";
import { ShiftReportView } from "../components/ShiftReportView";
import type { ShiftReport } from "../types";

const schema = z
  .object({ outcome: z.enum(["approved", "flagged"]), note: z.string().trim().max(1000) })
  .superRefine((v, ctx) => {
    if (v.outcome === "flagged" && !v.note) {
      ctx.addIssue({ code: "custom", path: ["note"], message: vmsg("validation.required") });
    }
  });

/** One shift's report; a manager signs it off here (FEATURES 7.5). */
export function ShiftDetailPage() {
  const { t } = useTranslation(["cashier", "common", "errors"]);
  const translateError = useTranslateError();
  const { shiftId } = useParams({ strict: false });
  const id = Number(shiftId);
  const shift = useShift(id);
  const canReview = usePermission("payments.review_shift");

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader
        title={
          shift.data ? (
            t("shiftDetail.title", { number: shift.data.shift.number })
          ) : (
            <Skeleton className="h-7 w-48" aria-label={t("common:loading")} />
          )
        }
        description={
          shift.data
            ? t(shift.data.shift.status === "open" ? "shiftDetail.descriptionOpen" : "shiftDetail.description")
            : undefined
        }
        icon={<ClipboardCheck />}
        actions={
          <Button
            variant="outline"
            onClick={() => {
              window.print();
            }}
            className="print:hidden"
          >
            <Printer aria-hidden="true" />
            {t("common:actions.print")}
          </Button>
        }
      />
      <CashierNav />
      {shift.isPending ? (
        <Skeleton className="h-64 w-full rounded-card" />
      ) : shift.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(shift.error)}
        </AlertCard>
      ) : (
        <>
          {/* The figures first, then the sign-off that asks the manager to check them. */}
          <PrintArea>
            <ShiftReportView report={shift.data} />
          </PrintArea>
          {canReview && shift.data.shift.status === "closed" && !shift.data.shift.review ? (
            <ReviewForm report={shift.data} />
          ) : null}
        </>
      )}
    </div>
  );
}

function ReviewForm({ report }: { report: ShiftReport }) {
  const { t } = useTranslation(["cashier", "common", "errors"]);
  const translateError = useTranslateError();
  const review = useReviewShift();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: { outcome: "approved", note: "" },
  });
  const submit = form.handleSubmit(async (v) => {
    setError(null);
    try {
      await review.mutateAsync({ shiftId: report.shift.id, body: v });
    } catch (e) {
      setError(translateError(e));
    }
  });
  return (
    <section
      className="card-surface flex min-w-0 flex-col gap-3 p-4 md:p-5 print:hidden"
      aria-labelledby="review-title"
    >
      <h2 id="review-title" className="text-base font-semibold">
        {t("review.formTitle")}
      </h2>
      <p className="text-sm text-muted">{t("review.formDescription")}</p>
      <Form {...form}>
        <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4" data-testid="review-form">
          <RadioGroupField
            control={form.control}
            name="outcome"
            label={t("review.outcomeLabel")}
            options={[
              { value: "approved", label: t("review.outcome.approved") },
              { value: "flagged", label: t("review.outcome.flagged") },
            ]}
          />
          <TextareaField control={form.control} name="note" label={t("common:reason.note")} rows={2} />
          {error ? (
            <AlertCard variant="danger" title={t("errors:title")} live>
              {error}
            </AlertCard>
          ) : null}
          <div className="flex justify-end">
            <Button type="submit" loading={form.formState.isSubmitting} data-testid="sign-off">
              {t("review.submit")}
            </Button>
          </div>
        </form>
      </Form>
    </section>
  );
}
