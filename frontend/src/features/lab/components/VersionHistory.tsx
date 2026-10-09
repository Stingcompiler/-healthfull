import { Link } from "@tanstack/react-router";
import { History, Printer } from "lucide-react";
import { useTranslation } from "react-i18next";

import { DateText } from "@/components/DateText";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { usePermission } from "@/lib/auth/hooks";

import { useLabNames } from "../lib/use-lab-names";
import type { LabResult, ResultVersion } from "../types";
import { ResultValues } from "./ResultValues";

function VersionBadge({ version }: { version: ResultVersion }) {
  const { t } = useTranslation("lab");
  if (version.status === "approved") return <Badge variant="success">{t("versions.current")}</Badge>;
  if (version.status === "amended") return <Badge variant="neutral">{t("versions.superseded")}</Badge>;
  return <Badge variant="warning">{t("versions.draft")}</Badge>;
}

/**
 * Every version of a result, newest first (FEATURES 9.5): an amendment never replaces the
 * original, which stays on record as superseded with who amended it and why.
 */
export function VersionHistory({ result, showDraft = true }: { result: LabResult; showDraft?: boolean }) {
  const { t } = useTranslation("lab");
  const names = useLabNames();
  const canPrint = usePermission("lab.print_results");
  const versions = [...result.versions].reverse().filter((v) => showDraft || v.status !== "draft");
  if (versions.length === 0) return null;
  return (
    <section className="card-surface flex min-w-0 flex-col gap-3 p-4 md:p-5" data-testid="version-history">
      <h2 className="flex items-center gap-2 text-base font-semibold">
        <History className="size-4 text-muted" aria-hidden="true" />
        {t("versions.title")}
      </h2>
      <ol className="flex flex-col gap-3">
        {versions.map((v) => (
          <li
            key={v.id}
            className="flex min-w-0 flex-col gap-2 rounded-control border border-border p-3"
            data-testid="result-version"
            data-status={v.status}
            data-version={v.version_no}
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="flex flex-wrap items-center gap-2 font-semibold">
                {t("versions.number", { number: v.version_no })}
                <VersionBadge version={v} />
              </span>
              {canPrint && v.status !== "draft" ? (
                <Button asChild variant="ghost" size="sm">
                  <Link
                    to="/lab/results/$lineId/print"
                    params={{ lineId: String(result.line.id) }}
                    search={v.status === "approved" ? {} : { version: v.id }}
                    data-testid="print-version"
                  >
                    <Printer aria-hidden="true" />
                    {t("versions.print")}
                  </Link>
                </Button>
              ) : null}
            </div>
            {v.amends_version_no !== null ? (
              <p className="text-xs text-muted" data-testid="amendment-reason">
                {t("versions.amends", { number: v.amends_version_no })}: {names.reason(v.amendment_reason)}
                {v.amendment_note ? ` · ${v.amendment_note}` : ""}
              </p>
            ) : null}
            <dl className="grid gap-x-4 gap-y-0.5 text-xs text-muted sm:grid-cols-2">
              <div className="flex flex-wrap gap-1">
                <dt>{t("versions.entered")}</dt>
                <dd>
                  {names.user(v.entered_by)} · <DateText value={v.entered_at} format="datetime" />
                </dd>
              </div>
              {v.approved_at ? (
                <div className="flex flex-wrap gap-1">
                  <dt>{t("versions.approved")}</dt>
                  <dd>
                    {names.user(v.approved_by)} · <DateText value={v.approved_at} format="datetime" />
                  </dd>
                </div>
              ) : null}
              {v.superseded_at ? (
                <div className="flex flex-wrap gap-1">
                  <dt>{t("versions.supersededBy")}</dt>
                  <dd>
                    {names.user(v.superseded_by)} · <DateText value={v.superseded_at} format="datetime" />
                  </dd>
                </div>
              ) : null}
            </dl>
            <ResultValues values={v.values} />
            {v.comment ? <p className="text-sm text-fg-muted">{v.comment}</p> : null}
          </li>
        ))}
      </ol>
    </section>
  );
}
