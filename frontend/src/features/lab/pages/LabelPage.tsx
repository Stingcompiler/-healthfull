import { Link, useParams, useSearch } from "@tanstack/react-router";
import { Tag } from "lucide-react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { ArrowBack } from "@/components/icons";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { QrCode } from "@/features/cashier/components/QrCode";
import { useTranslateError } from "@/lib/api/translate-error";
import { formatDate } from "@/lib/format";
import { useLanguage } from "@/lib/i18n-hooks";

import { useMarkLabelPrinted, useSampleLabel } from "../api";
import { LabPrintFrame } from "../components/LabPrintFrame";
import { useLabNames } from "../lib/use-lab-names";
import { parseLabelSearch } from "../lib/search";
import type { LabLabel } from "../types";

function sexMark(sex: string): string {
  return sex === "male" ? "M" : sex === "female" ? "F" : "";
}

/** The tube label: accession number as text and QR, patient, file, tests and collection time. */
function LabelBody({ label }: { label: LabLabel }) {
  const names = useLabNames();
  const language = useLanguage();
  const s = label.sample;
  return (
    <div className="flex items-start gap-1.5" data-testid="sample-label">
      <QrCode value={s.accession_no} label={s.accession_no} className="size-[18mm] shrink-0" />
      <div className="flex min-w-0 flex-col">
        <bdi dir="ltr" className="text-[12px] font-bold" data-testid="label-accession">
          {s.accession_no}
        </bdi>
        <span className="truncate font-semibold">{names.patient(label.patient)}</span>
        <span>
          <bdi dir="ltr">{label.patient.file_no}</bdi>
          {label.patient.date_of_birth ? (
            <>
              {" · "}
              <bdi dir="ltr">{label.patient.date_of_birth}</bdi>
            </>
          ) : null}
          {sexMark(label.patient.sex) ? ` · ${sexMark(label.patient.sex)}` : ""}
        </span>
        <bdi dir="ltr" className="truncate">
          {label.tests.map((t) => t.code).join(" ")}
        </bdi>
        <span>{formatDate(s.collected_at, language, "datetime")}</span>
      </div>
    </div>
  );
}

/** Prints the label of a sample (FEATURES 9.2) and records that it was printed. */
export function LabelPage() {
  const { t } = useTranslation(["lab", "errors"]);
  const translateError = useTranslateError();
  const { sampleId } = useParams({ strict: false });
  const search = parseLabelSearch(useSearch({ strict: false }));
  const id = Number(sampleId);
  const label = useSampleLabel(id);
  const printed = useMarkLabelPrinted(id);
  const names = useLabNames();

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader
        title={t("label.title")}
        description={t("label.description")}
        icon={<Tag />}
        className="print:hidden"
        actions={
          <Button asChild variant="outline">
            {search.line ? (
              <Link to="/lab/results/$lineId" params={{ lineId: String(search.line) }}>
                <ArrowBack aria-hidden="true" />
                {t("label.back")}
              </Link>
            ) : (
              <Link to="/lab">
                <ArrowBack aria-hidden="true" />
                {t("result.back")}
              </Link>
            )}
          </Button>
        }
      />
      {label.isPending ? (
        <Skeleton className="mx-auto h-32 w-full max-w-[50mm]" />
      ) : label.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(label.error)}
        </AlertCard>
      ) : (
        <>
          <dl className="grid gap-1 text-sm print:hidden">
            <div className="flex flex-wrap gap-2">
              <dt className="text-muted">{t("label.tests")}</dt>
              <dd>{names.list(label.data.tests.map((x) => names.test(x)))}</dd>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <dt className="text-muted">{t("label.status")}</dt>
              <dd>
                {label.data.sample.label_printed_at ? (
                  <Badge variant="success" data-testid="label-printed">
                    {t("label.printedAt", {
                      at: formatDate(label.data.sample.label_printed_at, names.language, "datetime"),
                    })}
                  </Badge>
                ) : (
                  <Badge variant="neutral">{t("label.notPrinted")}</Badge>
                )}
              </dd>
            </div>
          </dl>
          <LabPrintFrame
            paper="label"
            testId="label-paper"
            onPrint={() => {
              printed.mutate();
            }}
          >
            <LabelBody label={label.data} />
          </LabPrintFrame>
        </>
      )}
    </div>
  );
}
