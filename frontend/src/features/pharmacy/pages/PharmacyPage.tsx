import { Pill, ScanLine } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type SyntheticEvent } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { DateText } from "@/components/DateText";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";
import { usePermission } from "@/lib/auth/hooks";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";

import { queueQuery, usePharmacyOptions, useQueue } from "../api";
import { LabeledField, QtyText, StoreSelect } from "../components/common";
import { DispenseDialog } from "../components/DispenseDialog";
import { PharmacyNav } from "../components/PharmacyNav";
import { useNames } from "../lib/use-names";
import type { QueueVisit } from "../types";

/**
 * The dispense queue (FLOW 6, FEATURES 8.3): only paid or perform-first authorized drug and
 * consumable lines appear (invariant 1). A barcode scanner types the visit, file or invoice
 * number and Enter; a single match opens the dispense dialog.
 */
export function PharmacyPage() {
  const { t } = useTranslation(["pharmacy", "errors"]);
  const translateError = useTranslateError();
  const canDispense = usePermission("pharmacy.dispense");
  const options = usePharmacyOptions();
  const queryClient = useQueryClient();
  const [input, setInput] = useState("");
  const [chosenStore, setChosenStore] = useState<number | undefined>(undefined);
  const storeId = chosenStore ?? options.data?.default_store_id ?? undefined;
  const [openVisit, setOpenVisit] = useState<number | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  // Type-ahead: the list narrows while typing.
  const query = useDebouncedValue(input.trim(), 350);
  const queue = useQueue(query);

  /** Enter (what a scanner sends) searches now; a single match opens the prescription. */
  const onSubmit = async (e: SyntheticEvent) => {
    e.preventDefault();
    const term = input.trim();
    if (!term) return;
    try {
      const found = await queryClient.query(queueQuery(term));
      if (found.length === 1 && found[0]) setOpenVisit(found[0].visit_id);
    } catch {
      // The list below shows the error of the same query.
    }
  };

  if (!canDispense) {
    return (
      <div className="flex min-w-0 flex-col gap-4">
        <PageHeader title={t("queue.title")} icon={<Pill />} />
        <PharmacyNav />
        <AlertCard variant="info" title={t("queue.noAccessTitle")}>
          {t("queue.noAccess")}
        </AlertCard>
      </div>
    );
  }

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <PageHeader title={t("queue.title")} description={t("queue.description")} icon={<Pill />} />
      <PharmacyNav />
      <div className="card-surface grid gap-3 p-4 md:grid-cols-[minmax(0,1fr)_16rem] md:items-end md:p-5">
        <form onSubmit={(e) => void onSubmit(e)} role="search" className="flex items-end gap-2">
          <LabeledField label={t("queue.scanLabel")} className="flex-1">
            {(id) => (
              <Input
                id={id}
                ref={inputRef}
                type="search"
                value={input}
                autoFocus
                autoComplete="off"
                placeholder={t("queue.scanPlaceholder")}
                data-testid="queue-scan"
                onChange={(e) => {
                  setInput(e.target.value);
                }}
              />
            )}
          </LabeledField>
          <Button type="submit" variant="outline" aria-label={t("queue.scanSubmit")}>
            <ScanLine aria-hidden="true" />
          </Button>
        </form>
        <StoreSelect
          stores={options.data?.stores ?? []}
          value={storeId}
          onChange={setChosenStore}
          label={t("queue.store")}
          onlyDispensing
          testId="queue-store"
        />
        <p className="text-xs text-muted md:col-span-2">{t("queue.scanHint")}</p>
      </div>

      {queue.isError ? (
        <AlertCard variant="danger" title={t("errors:title")}>
          {translateError(queue.error)}
        </AlertCard>
      ) : queue.isPending ? (
        <div className="grid gap-3">
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
        </div>
      ) : queue.data.length === 0 ? (
        <EmptyState
          icon={<Pill />}
          title={query ? t("queue.noMatch") : t("queue.empty")}
          description={query ? t("queue.noMatchHint") : t("queue.emptyHint")}
        />
      ) : (
        <ul className="grid gap-3" aria-label={t("queue.listLabel")} data-testid="queue-list">
          {queue.data.map((visit) => (
            <QueueCard
              key={visit.visit_id}
              visit={visit}
              onOpen={() => {
                setOpenVisit(visit.visit_id);
              }}
            />
          ))}
        </ul>
      )}

      <DispenseDialog
        visitId={openVisit}
        storeId={storeId}
        onClose={() => {
          setOpenVisit(null);
          setInput("");
          inputRef.current?.focus();
        }}
      />
    </div>
  );
}

function QueueCard({ visit, onOpen }: { visit: QueueVisit; onOpen: () => void }) {
  const { t } = useTranslation("pharmacy");
  const names = useNames();
  return (
    <li className="card-surface grid gap-3 p-4" data-testid="queue-visit" data-visit-number={visit.visit_number}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="grid min-w-0 gap-1">
          <p className="text-base font-semibold break-words">{names.person(visit.patient)}</p>
          <p className="flex flex-wrap gap-x-3 gap-y-1 text-sm text-muted">
            <bdi>{visit.patient.file_no}</bdi>
            <bdi>{visit.visit_number}</bdi>
            <DateText value={visit.created_at} format="datetime" />
            {visit.visit_type === "pharmacy_sale" ? <Badge variant="info">{t("queue.walkIn")}</Badge> : null}
          </p>
        </div>
        <Button onClick={onOpen} data-testid="queue-dispense">
          <Pill aria-hidden="true" />
          {t("queue.dispense")}
        </Button>
      </div>
      <ul className="grid gap-1.5 text-sm">
        {visit.lines.map((line) => (
          <li key={line.id} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
            <span className="min-w-0 break-words">{names.name(line.service)}</span>
            <span className="flex flex-wrap items-center gap-2">
              {line.authorized ? <Badge variant="warning">{t("queue.authorized")}</Badge> : null}
              {line.started ? <Badge variant="info">{t("queue.started")}</Badge> : null}
              {line.item_id === null ? <Badge variant="danger">{t("dispense.notStocked")}</Badge> : null}
              <QtyText value={line.remaining} unit={names.baseUnit(line)} className="font-medium" />
            </span>
          </li>
        ))}
      </ul>
    </li>
  );
}
