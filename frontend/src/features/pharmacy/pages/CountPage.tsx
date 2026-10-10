import { Link, useParams } from "@tanstack/react-router";
import { ClipboardList, Save } from "lucide-react";
import { useState, type SyntheticEvent } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { ChevronPrev } from "@/components/icons";
import { MoneyText } from "@/components/MoneyText";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";
import { usePermission } from "@/lib/auth/hooks";
import { formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";

import { useCount, useCountAction, useRecordCount } from "../api";
import { DocStatusBadge, ErrorAlert, QtyText } from "../components/common";
import { PharmacyNav } from "../components/PharmacyNav";
import { parseWhole } from "../lib/qty";
import { useNames } from "../lib/use-names";
import type { StockCount, StockCountLine } from "../types";

/**
 * One count session (FEATURES 8.7): enter what is on the shelf per batch; the book quantity
 * is taken again at each entry, and posting turns variances into count corrections.
 */
export function CountPage() {
  const { countId } = useParams({ from: "/_app/pharmacy/counts/$countId" });
  const { t } = useTranslation(["pharmacy", "errors"]);
  const translateError = useTranslateError();
  const count = useCount(Number(countId));

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader
        title={count.data ? t("count.title", { number: count.data.number }) : t("counts.title")}
        icon={<ClipboardList />}
        eyebrow={
          <Link
            to="/pharmacy/counts"
            className="inline-flex items-center gap-1 text-sm text-primary-strong hover:underline"
          >
            <ChevronPrev className="size-4" />
            {t("count.back")}
          </Link>
        }
      />
      <PharmacyNav />
      {count.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(count.error)}
        </AlertCard>
      ) : count.isPending ? (
        <Skeleton className="h-64" />
      ) : (
        <CountSheet count={count.data} />
      )}
    </div>
  );
}

function CountSheet({ count }: { count: StockCount }) {
  const { t } = useTranslation(["pharmacy", "common"]);
  const names = useNames();
  const canCount = usePermission("pharmacy.count_stock");
  const canPost = usePermission("pharmacy.post_count");
  const action = useCountAction();
  const [confirm, setConfirm] = useState<"post" | "cancel" | null>(null);
  const open = count.status === "open";

  return (
    <div className="grid gap-4">
      <section className="card-surface grid gap-3 p-4 md:p-5" data-testid="count-summary">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <DocStatusBadge status={count.status} kind="count" />
            <span className="text-sm text-muted">{names.name(count.store)}</span>
            <span className="text-sm text-muted">
              {names.person(count.started_by)} · <DateText value={count.started_at} format="datetime" />
            </span>
          </div>
          {open ? (
            <div className="flex flex-wrap gap-2">
              {canCount ? (
                <Button
                  variant="destructive-soft"
                  onClick={() => {
                    setConfirm("cancel");
                  }}
                >
                  {t("count.cancel")}
                </Button>
              ) : null}
              {canPost ? (
                <Button
                  onClick={() => {
                    setConfirm("post");
                  }}
                  data-testid="count-post"
                >
                  {t("count.post")}
                </Button>
              ) : null}
            </div>
          ) : null}
        </div>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-muted">{t("count.counted")}</dt>
            <dd className="tabular font-semibold" data-testid="count-progress">
              {t("counts.progress", {
                counted: formatNumber(count.counted, names.language),
                total: formatNumber(count.total, names.language),
              })}
            </dd>
          </div>
          <div>
            <dt className="text-muted">{t("count.varianceValue")}</dt>
            <dd className="font-semibold">
              <MoneyText value={count.variance_value} signed toneNegative />
            </dd>
          </div>
          {count.posted_by ? (
            <div>
              <dt className="text-muted">{t("count.postedBy")}</dt>
              <dd>{names.person(count.posted_by)}</dd>
            </div>
          ) : null}
        </dl>
        {open && !canPost ? <p className="text-sm text-muted">{t("count.postHint")}</p> : null}
      </section>

      {count.lines.length === 0 ? (
        <EmptyState icon={<ClipboardList />} title={t("count.noLines")} />
      ) : (
        <ul className="grid gap-2" aria-label={t("count.lines")}>
          {count.lines.map((line) => (
            <CountLineRow key={line.id} count={count} line={line} editable={open && canCount} />
          ))}
        </ul>
      )}

      <ConfirmDialog
        open={confirm !== null}
        onOpenChange={(o) => {
          if (!o) setConfirm(null);
        }}
        title={confirm === "post" ? t("count.postTitle") : t("count.cancelTitle")}
        description={confirm === "post" ? t("count.postDescription") : t("count.cancelDescription")}
        confirmLabel={confirm === "post" ? t("count.post") : t("count.cancel")}
        destructive={confirm === "cancel"}
        onConfirm={async () => {
          if (confirm) await action.mutateAsync({ countId: count.id, action: confirm });
        }}
      />
    </div>
  );
}

function CountLineRow({ count, line, editable }: { count: StockCount; line: StockCountLine; editable: boolean }) {
  const { t } = useTranslation(["pharmacy", "common"]);
  const translateError = useTranslateError();
  const names = useNames();
  const record = useRecordCount();
  const [value, setValue] = useState(line.counted_qty === null ? "" : String(line.counted_qty));
  const [error, setError] = useState<string | null>(null);
  const unit = names.baseUnit(line);
  const inputId = `count-${String(line.id)}`;

  const save = async (e: SyntheticEvent) => {
    e.preventDefault();
    setError(null);
    const counted = parseWhole(value, 0);
    if (counted === null) {
      setError(t("validation.wholeNumber"));
      return;
    }
    try {
      await record.mutateAsync({ countId: count.id, batchId: line.batch_id, counted });
    } catch (err) {
      setError(translateError(err));
    }
  };

  return (
    <li
      className="card-surface grid gap-3 p-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center sm:p-4"
      data-testid="count-line"
      data-batch-no={line.batch_no}
    >
      <div className="grid min-w-0 gap-1">
        <p className="font-medium break-words">{line.item_name}</p>
        <p className="flex flex-wrap gap-x-3 gap-y-1 text-sm text-muted">
          <span>
            {t("batch.number")} <bdi>{line.batch_no}</bdi>
          </span>
          <span>
            {t("batch.expiry")} <DateText value={line.expiry_date} />
          </span>
          <span>
            {t("count.book")} <QtyText value={line.book_qty} unit={unit} className="text-fg" />
          </span>
          {line.variance !== null ? (
            <span
              className={cn(
                "font-medium",
                line.variance < 0 ? "text-danger-fg" : line.variance > 0 ? "text-success-fg" : "text-fg",
              )}
              data-testid="count-variance"
            >
              {t("count.variance")}{" "}
              <bdi className="tabular">
                {(line.variance > 0 ? "+" : "") + formatNumber(line.variance, names.language)}
              </bdi>
            </span>
          ) : null}
        </p>
      </div>
      {editable ? (
        <form onSubmit={(e) => void save(e)} className="grid gap-1">
          <Label htmlFor={inputId} className="text-xs">
            {t("count.countedQty", { unit })}
          </Label>
          <div className="flex items-center gap-2">
            <Input
              id={inputId}
              value={value}
              className="w-28"
              inputMode="numeric"
              dir="ltr"
              aria-invalid={error ? true : undefined}
              data-testid="count-input"
              onChange={(e) => {
                setValue(e.target.value);
              }}
            />
            <Button type="submit" variant="outline" loading={record.isPending} data-testid="count-save">
              <Save aria-hidden="true" />
              {t("common:actions.save")}
            </Button>
          </div>
          {error ? <ErrorAlert message={error} /> : null}
        </form>
      ) : line.counted_qty !== null ? (
        <p className="text-sm">
          {t("count.counted")} <QtyText value={line.counted_qty} unit={unit} className="font-semibold" />
        </p>
      ) : null}
    </li>
  );
}
