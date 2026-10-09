import { ClipboardList, Send, Star } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { AlertCard } from "@/components/AlertCard";
import { Can } from "@/components/Can";
import { EmptyState } from "@/components/EmptyState";
import { KbdCombo } from "@/components/Kbd";
import { ReasonDialog } from "@/components/ReasonDialog";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTranslateError } from "@/lib/api/translate-error";
import { usePermission } from "@/lib/auth/hooks";
import { useShortcut } from "@/lib/hooks/use-shortcut";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

import { useAllergyAlerts, useCreateLines, useVisitLines, useWithdrawLine, useWithdrawReasons } from "../api";
import { draftFromService, draftsFromOrderSet, toOrderItem, type DraftItem } from "../draft";
import { allergyConflict } from "../lib";
import type { AllergyAlert, DoctorLine } from "../types";
import { AllergyOverrideDialog } from "./AllergyOverrideDialog";
import { CatalogPicker } from "./CatalogPicker";
import { DraftItemEditor } from "./DraftItemEditor";
import { EstimatePanel } from "./EstimatePanel";
import { FavoriteDialog } from "./FavoriteDialog";
import { OrderLineCard } from "./OrderLineCard";
import { OrderSetPicker } from "./OrderSetPicker";
import { QueryError } from "./QueryError";

const PLACE_SHORTCUT = "mod+enter";

/**
 * Orders of the visit (FEATURES 3.5-3.7, 4.1, 4.2): write an order from the catalog, order sets
 * and favorites (drugs through the prescription builder), place it, and follow each line's
 * status. A drug matching an allergy needs an override reason.
 */
export function OrdersTab({
  visitId,
  patientId,
  open,
  active = true,
  onDraftChange,
}: {
  visitId: number;
  patientId: number;
  open: boolean;
  /** The tab is showing (it stays mounted while hidden); its shortcuts work only then. */
  active?: boolean;
  /** Tells the page how many draft items are not placed (finishing the consultation warns). */
  onDraftChange?: (count: number) => void;
}) {
  const { t } = useTranslation("clinic");
  const language = useLanguage();
  const canOrder = usePermission("orders.create") && open;
  const canWithdraw = usePermission("orders.cancel_line");
  const lines = useVisitLines(visitId);
  const create = useCreateLines(visitId, patientId);
  const withdraw = useWithdrawLine(visitId);
  const translateError = useTranslateError();
  const [draft, setDraft] = useState<DraftItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [alerts, setAlerts] = useState<AllergyAlert[] | null>(null);
  // The matches the server refused at placing: they stay marked on their draft items after the
  // override dialog is dismissed, until the item is removed or the orders are placed.
  const [conflicts, setConflicts] = useState<AllergyAlert[]>([]);
  const [favoriteOpen, setFavoriteOpen] = useState(false);
  const [withdrawing, setWithdrawing] = useState<DoctorLine | null>(null);
  const reasons = useWithdrawReasons(withdrawing !== null);
  const draftRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    onDraftChange?.(draft.length);
  }, [draft.length, onDraftChange]);

  const add = (items: DraftItem[]) => {
    setError(null);
    setDraft((prev) => [...prev, ...items]);
  };

  const place = async (overrideReason = "") => {
    if (draft.length === 0) return;
    setError(null);
    try {
      await create.mutateAsync({
        items: draft.map((item) => toOrderItem(item, language)),
        allergy_override_reason: overrideReason,
      });
      setDraft([]);
      setAlerts(null);
      setConflicts([]);
      toast.success(t("orders.placedToast", { count: draft.length }));
    } catch (e) {
      // With an override reason the dialog is open: it shows the error itself.
      if (overrideReason) throw e;
      const conflict = allergyConflict(e);
      if (conflict) {
        setAlerts(conflict);
        setConflicts(conflict);
        return;
      }
      setError(translateError(e));
    }
  };

  // Never behind this tab's dialogs (the override dialog has its own Ctrl/Cmd+Enter).
  const dialogOpen = alerts !== null || favoriteOpen || withdrawing !== null;
  useShortcut(PLACE_SHORTCUT, () => void place(), {
    enabled: active && canOrder && draft.length > 0 && !dialogOpen,
    allowInInputs: true,
  });

  // Drugs matching an allergy are marked as soon as they are added (a warning from the server's
  // own matcher); placing them still needs an override reason.
  const drugIds = [...new Set(draft.filter((d) => d.rx).map((d) => d.serviceId))].sort((a, b) => a - b);
  const liveAlerts = useAllergyAlerts(canOrder ? patientId : undefined, drugIds);
  const matches = new Map<number, AllergyAlert[]>();
  for (const alert of [...(liveAlerts.data ?? []), ...conflicts]) {
    const known = matches.get(alert.service_id) ?? [];
    if (!known.some((a) => a.allergy_id === alert.allergy_id)) matches.set(alert.service_id, [...known, alert]);
  }

  return (
    <div className="@container flex flex-col gap-4">
      {canOrder ? (
        <section aria-labelledby="new-order-heading" className="card-surface flex flex-col gap-4 p-4 md:p-5">
          <div className="flex items-center gap-2">
            <ClipboardList className="size-4 text-muted" aria-hidden="true" />
            <h2 id="new-order-heading" className="text-base font-semibold text-fg">
              {t("orders.newOrder")}
            </h2>
          </div>
          <div className="grid gap-4 @3xl:grid-cols-2">
            <CatalogPicker
              active={active}
              patientId={patientId}
              onPick={(service) => add([draftFromService(service)])}
            />
            <OrderSetPicker onPick={(set) => add(draftsFromOrderSet(set))} />
          </div>

          <div ref={draftRef} className="flex flex-col gap-3" data-testid="draft">
            {draft.length === 0 ? (
              <p className="rounded-control border border-dashed border-border p-4 text-center text-sm text-muted">
                {t("orders.draftEmpty")}
              </p>
            ) : (
              <ul className="flex flex-col gap-2">
                {draft.map((item) => (
                  <DraftItemEditor
                    key={item.key}
                    item={item}
                    allergyMatches={matches.get(item.serviceId) ?? []}
                    onChange={(next) => setDraft((prev) => prev.map((d) => (d.key === next.key ? next : d)))}
                    onRemove={() => setDraft((prev) => prev.filter((d) => d.key !== item.key))}
                  />
                ))}
              </ul>
            )}
            {error ? (
              <AlertCard variant="danger" live title={t("orders.placeError")}>
                {error}
              </AlertCard>
            ) : null}
            <Can permission="clinical.view_estimated_cost">
              <EstimatePanel
                key={draft.map((d) => `${d.key}:${JSON.stringify(toOrderItem(d, language))}`).join("|")}
                visitId={visitId}
                draft={draft}
              />
            </Can>
            <div className="flex flex-wrap items-center justify-end gap-2">
              <Button
                variant="ghost"
                disabled={draft.length === 0}
                onClick={() => setFavoriteOpen(true)}
                data-testid="save-favorite"
              >
                <Star aria-hidden="true" />
                {t("orders.saveFavorite")}
              </Button>
              <Button
                onClick={() => void place()}
                loading={create.isPending}
                disabled={draft.length === 0}
                data-testid="place-orders"
              >
                <Send aria-hidden="true" />
                {draft.length > 0 ? t("orders.place", { count: draft.length }) : t("orders.placeEmpty")}
                <KbdCombo combo={PLACE_SHORTCUT} className="max-md:hidden" />
              </Button>
            </div>
          </div>
        </section>
      ) : null}

      <section aria-labelledby="orders-heading" className="flex flex-col gap-3">
        <h2 id="orders-heading" className="text-sm font-semibold text-fg-muted">
          {t("orders.current")}
        </h2>
        {lines.isError ? (
          <QueryError
            title={t("orders.loadError")}
            error={lines.error}
            onRetry={() => void lines.refetch()}
            retrying={lines.isFetching}
          />
        ) : !lines.data ? (
          <Skeleton className="h-28" />
        ) : lines.data.length === 0 ? (
          <EmptyState
            size="compact"
            icon={<ClipboardList />}
            title={t("orders.noneTitle")}
            description={t("orders.noneDescription")}
          />
        ) : (
          <ul className="grid gap-3 @3xl:grid-cols-2" data-testid="order-lines">
            {lines.data.map((line) => (
              <li key={line.id} className="min-w-0">
                <OrderLineCard line={line} onWithdraw={canWithdraw && open ? setWithdrawing : undefined} />
              </li>
            ))}
          </ul>
        )}
      </section>

      <AllergyOverrideDialog
        key={alerts ? "alert" : "none"}
        alerts={alerts}
        names={new Map(draft.map((d) => [d.serviceId, pickName({ ar: d.nameAr, en: d.nameEn }, language)]))}
        onCancel={() => setAlerts(null)}
        onConfirm={(reason) => place(reason)}
      />
      <FavoriteDialog open={favoriteOpen} onOpenChange={setFavoriteOpen} items={draft} />
      <ReasonDialog
        open={withdrawing !== null}
        onOpenChange={(o) => {
          if (!o) setWithdrawing(null);
        }}
        title={t("orders.withdrawTitle")}
        description={withdrawing ? pickName({ ar: withdrawing.name_ar, en: withdrawing.name_en }, language) : undefined}
        reasons={(reasons.data ?? []).map((r) => ({
          code: r.code,
          label: pickName({ ar: r.label_ar, en: r.label_en }, language),
        }))}
        noteRequired={false}
        destructive
        confirmLabel={t("orders.withdraw")}
        onSubmit={async ({ code, note }) => {
          if (!withdrawing) return;
          await withdraw.mutateAsync({ lineId: withdrawing.id, reasonCode: code, note });
          setWithdrawing(null);
          toast.success(t("orders.withdrawnToast"));
        }}
      />
    </div>
  );
}
