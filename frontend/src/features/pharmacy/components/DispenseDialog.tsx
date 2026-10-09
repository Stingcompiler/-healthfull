import { CheckCircle2, ScanLine } from "lucide-react";
import { useRef, useState, type SyntheticEvent } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { DateText } from "@/components/DateText";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useTranslateError } from "@/lib/api/translate-error";
import { formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";

import { scanBarcode, useDispense, useDispenseVisit, usePharmacyOptions } from "../api";
import { approverPayload, NO_APPROVER, type ApproverState } from "../lib/approver";
import { REMAINDERS } from "../lib/constants";
import { parseWhole } from "../lib/qty";
import { useNames } from "../lib/use-names";
import type { Dispense, DispenseLineIn, DispenseLineOptions } from "../types";
import { ApproverInputs, ErrorAlert, ExpiryBadge, LabeledField, QtyText } from "./common";

type Remainder = "defer" | "refund";

interface LineState {
  include: boolean;
  qty: string;
  unit: string; // "" = base unit
  override: boolean;
  picks: Record<string, string>;
  reason: string;
  note: string;
  remainder: Remainder;
}

function initialLine(line: DispenseLineOptions, remainder: Remainder): LineState {
  return {
    include: line.item_id !== null && line.available > 0,
    qty: String(Math.min(line.remaining, line.available) || line.remaining),
    unit: "",
    override: false,
    picks: {},
    reason: "",
    note: "",
    remainder,
  };
}

function factorOf(line: DispenseLineOptions, unit: string): number {
  if (!unit) return 1;
  return line.units.find((u) => u.unit_code === unit)?.factor ?? 1;
}

/** Base units a line state asks for, or null when the quantity is not a whole number. */
function baseQty(line: DispenseLineOptions, state: LineState): number | null {
  const qty = parseWhole(state.qty);
  return qty === null ? null : qty * factorOf(line, state.unit);
}

/** Mounted only while open, so every opening starts from the visit's current lines. */
export function DispenseDialog(props: { visitId: number | null; storeId: number | undefined; onClose: () => void }) {
  return props.visitId !== null ? <DispenseDialogOpen {...props} visitId={props.visitId} /> : null;
}

/**
 * Dispense a visit's paid or authorized lines (FEATURES 8.2-8.4). The earliest-expiry batches
 * are used unless the pharmacist chooses others with a reason; a line given in part keeps its
 * rest open or has it cancelled and refunded with a supervisor's approval.
 */
function DispenseDialogOpen({
  visitId,
  storeId,
  onClose,
}: {
  visitId: number;
  storeId: number | undefined;
  onClose: () => void;
}) {
  const { t } = useTranslation(["pharmacy", "common", "errors"]);
  const translateError = useTranslateError();
  const names = useNames();
  const options = usePharmacyOptions();
  const visit = useDispenseVisit(visitId, storeId);
  const dispense = useDispense();
  const policy: Remainder = options.data?.partial_dispense_remainder ?? "defer";
  const [lines, setLines] = useState<Record<number, LineState>>({});
  const [note, setNote] = useState("");
  const [approver, setApprover] = useState<ApproverState>(NO_APPROVER);
  const [error, setError] = useState<string | null>(null);
  const [checked, setChecked] = useState(false);
  const [done, setDone] = useState<Dispense | null>(null);
  const [scan, setScan] = useState("");
  const [scanMessage, setScanMessage] = useState<string | null>(null);
  const qtyRefs = useRef<Record<number, HTMLInputElement | null>>({});
  const scanRef = useRef<HTMLInputElement>(null);

  const data = visit.data;
  /** A line's form state: what the pharmacist changed, else the defaults from the line. */
  const stateOf = (line: DispenseLineOptions): LineState => lines[line.id] ?? initialLine(line, policy);

  const included = (data?.lines ?? []).filter((l) => stateOf(l).include && l.item_id !== null);
  const needsApprover = included.some((l) => {
    const st = stateOf(l);
    const qty = baseQty(l, st);
    return st.remainder === "refund" && qty !== null && qty < l.remaining;
  });

  const update = (line: DispenseLineOptions, patch: Partial<LineState>) => {
    setLines((prev) => ({ ...prev, [line.id]: { ...(prev[line.id] ?? initialLine(line, policy)), ...patch } }));
  };

  /** A scanned item barcode picks its line (and the scanned pack unit). */
  const onScan = async (e: SyntheticEvent) => {
    e.preventDefault();
    const code = scan.trim();
    if (!code || !data) return;
    setScan("");
    try {
      const found = await scanBarcode(code);
      const line = data.lines.find((l) => l.item_id === found.item.id);
      if (!line) {
        setScanMessage(t("dispense.scanNotOnVisit", { name: found.item.generic_name }));
        return;
      }
      const scanned = found.unit_code;
      const usable = scanned !== null && line.units.some((u) => u.unit_code === scanned && u.is_dispensable);
      update(line, {
        include: true,
        unit: usable ? scanned : "",
        qty: usable ? "1" : String(line.remaining),
      });
      setScanMessage(t("dispense.scanFound", { name: names.name(line.service) }));
      qtyRefs.current[line.id]?.focus();
      qtyRefs.current[line.id]?.select();
    } catch (err) {
      setScanMessage(translateError(err));
    }
  };

  const problems = (line: DispenseLineOptions, st: LineState): string | null => {
    const qty = baseQty(line, st);
    if (qty === null) return t("dispense.qtyInvalid");
    if (qty > line.remaining) return t("dispense.qtyTooMuch", { max: line.remaining });
    if (st.override) {
      const total = Object.values(st.picks).reduce((sum, raw) => sum + (parseWhole(raw, 0) ?? Number.NaN), 0);
      if (Number.isNaN(total)) return t("dispense.pickInvalid");
      if (total !== qty) return t("dispense.pickMismatch", { chosen: total, needed: qty });
      if (!st.reason) return t("dispense.reasonRequired");
    }
    return null;
  };

  const submit = async (e: SyntheticEvent) => {
    e.preventDefault();
    setChecked(true);
    setError(null);
    if (!data) return;
    if (included.length === 0) {
      setError(t("dispense.nothingChosen"));
      return;
    }
    if (included.some((l) => problems(l, stateOf(l)) !== null)) return;
    const body: DispenseLineIn[] = included.map((l) => {
      const st = stateOf(l);
      const qty = baseQty(l, st) ?? 0;
      const picks = Object.entries(st.picks)
        .map(([batchId, raw]) => ({ batch_id: Number(batchId), quantity: parseWhole(raw, 0) ?? 0 }))
        .filter((p) => p.quantity > 0);
      return {
        service_line_id: l.id,
        quantity: parseWhole(st.qty) ?? 0,
        unit_code: st.unit || null,
        batches: st.override ? picks : null,
        override_reason: st.override ? st.reason : null,
        override_note: st.override ? st.note.trim() : "",
        remainder: qty < l.remaining ? st.remainder : null,
      };
    });
    try {
      const result = await dispense.mutateAsync({
        visit_id: data.visit_id,
        store_id: data.store.id,
        lines: body,
        note: note.trim(),
        approver: needsApprover ? approverPayload(approver) : null,
      });
      setDone(result);
    } catch (err) {
      setError(translateError(err));
    }
  };

  const patientName = data ? names.person(data.patient) : "";

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !dispense.isPending) onClose();
      }}
    >
      <DialogContent className="max-h-[92dvh] overflow-y-auto sm:max-w-3xl" data-testid="dispense-dialog">
        <DialogHeader>
          <DialogTitle>{t("dispense.dialogTitle")}</DialogTitle>
          <DialogDescription>
            {data ? (
              <span className="flex flex-wrap gap-x-3 gap-y-1">
                <span className="font-medium text-fg">{patientName}</span>
                <bdi>{data.patient.file_no}</bdi>
                <bdi>{data.visit_number}</bdi>
                <span>{names.name(data.store)}</span>
              </span>
            ) : (
              t("dispense.loading")
            )}
          </DialogDescription>
        </DialogHeader>

        {done ? (
          <DispenseDone result={done} onClose={onClose} />
        ) : visit.isPending ? (
          <div className="grid gap-3">
            <Skeleton className="h-24" />
            <Skeleton className="h-24" />
          </div>
        ) : visit.isError ? (
          <ErrorAlert message={translateError(visit.error)} />
        ) : data?.lines.length === 0 ? (
          <AlertCard variant="info" title={t("dispense.nothingLeftTitle")}>
            {t("dispense.nothingLeft")}
          </AlertCard>
        ) : data ? (
          <div className="grid gap-4">
            <form onSubmit={(e) => void onScan(e)} className="flex items-end gap-2" role="search">
              <LabeledField label={t("dispense.scanItem")} className="flex-1">
                {(id) => (
                  <Input
                    id={id}
                    ref={scanRef}
                    value={scan}
                    autoComplete="off"
                    dir="ltr"
                    inputMode="text"
                    placeholder={t("dispense.scanItemPlaceholder")}
                    data-testid="dispense-scan"
                    onChange={(e) => {
                      setScan(e.target.value);
                    }}
                  />
                )}
              </LabeledField>
              <Button type="submit" variant="outline" aria-label={t("dispense.scanSubmit")}>
                <ScanLine aria-hidden="true" />
              </Button>
            </form>
            {scanMessage ? (
              <p className="text-sm text-muted" role="status">
                {scanMessage}
              </p>
            ) : null}

            <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4" id="dispense-form">
              <ul className="grid gap-3">
                {data.lines.map((line) => {
                  const st = stateOf(line);
                  return (
                    <DispenseLineEditor
                      key={line.id}
                      line={line}
                      state={st}
                      error={checked && st.include ? problems(line, st) : null}
                      onChange={(patch) => {
                        update(line, patch);
                      }}
                      qtyRef={(el) => {
                        qtyRefs.current[line.id] = el;
                      }}
                      reasons={options.data?.reasons_override ?? []}
                    />
                  );
                })}
              </ul>
              {needsApprover ? (
                <ApproverInputs
                  value={approver}
                  onChange={setApprover}
                  description={t("dispense.approverDescription")}
                  testId="dispense-approver"
                />
              ) : null}
              <LabeledField label={t("dispense.note")}>
                {(id) => (
                  <Textarea
                    id={id}
                    rows={2}
                    maxLength={500}
                    value={note}
                    onChange={(e) => {
                      setNote(e.target.value);
                    }}
                  />
                )}
              </LabeledField>
              <ErrorAlert message={error} />
              <DialogFooter>
                <Button type="button" variant="outline" onClick={onClose}>
                  {t("common:actions.cancel")}
                </Button>
                <Button type="submit" loading={dispense.isPending} data-testid="dispense-submit">
                  {t("dispense.submit")}
                </Button>
              </DialogFooter>
            </form>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}

function DispenseLineEditor({
  line,
  state,
  error,
  onChange,
  qtyRef,
  reasons,
}: {
  line: DispenseLineOptions;
  state: LineState;
  error: string | null;
  onChange: (patch: Partial<LineState>) => void;
  qtyRef: (el: HTMLInputElement | null) => void;
  reasons: readonly { code: string; label_ar: string; label_en: string }[];
}) {
  const { t } = useTranslation("pharmacy");
  const names = useNames();
  const unitName = names.baseUnit(line);
  const stocked = line.item_id !== null;
  const qty = baseQty(line, state);
  const partial = qty !== null && qty < line.remaining;
  const fefo = new Map((line.fefo ?? []).map((p) => [p.batch_id, p.quantity]));
  const includeId = `dispense-include-${String(line.id)}`;
  const overrideId = `dispense-override-${String(line.id)}`;
  const dispensable = line.units.filter((u) => u.is_dispensable);
  const firstUsable = line.batches.find((bt) => !bt.expired)?.batch_id;

  return (
    <li
      className={cn("card-surface grid gap-3 p-3 sm:p-4", !state.include && "opacity-80")}
      data-testid="dispense-line"
      data-line-id={line.id}
    >
      <div className="flex items-start gap-3">
        <Checkbox
          id={includeId}
          checked={state.include}
          disabled={!stocked}
          onCheckedChange={(v) => {
            onChange({ include: v === true });
          }}
          className="mt-1"
        />
        <div className="grid min-w-0 flex-1 gap-1">
          <Label htmlFor={includeId} className="text-base font-semibold break-words">
            {names.name(line.service)}
          </Label>
          <p className="flex flex-wrap gap-x-3 gap-y-1 text-sm text-muted">
            <span>
              {t("dispense.remaining")} <QtyText value={line.remaining} unit={unitName} className="text-fg" />
            </span>
            {line.dispensed > 0 ? (
              <span>
                {t("dispense.alreadyGiven")} <QtyText value={line.dispensed} unit={unitName} />
              </span>
            ) : null}
            <span>
              {t("dispense.available")} <QtyText value={line.available} unit={unitName} />
            </span>
          </p>
          {line.prescription ? (
            <p className="text-sm break-words">
              {[
                line.prescription.dose,
                line.prescription.frequency_code,
                line.prescription.duration_days !== null
                  ? t("dispense.days", { count: line.prescription.duration_days })
                  : "",
                line.prescription.instructions,
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
          ) : null}
          <div className="flex flex-wrap gap-1.5">
            {line.authorized ? <Badge variant="warning">{t("queue.authorized")}</Badge> : null}
            {!stocked ? <Badge variant="danger">{t("dispense.notStocked")}</Badge> : null}
            {stocked && line.available < line.remaining ? <Badge variant="warning">{t("dispense.short")}</Badge> : null}
          </div>
        </div>
      </div>

      {state.include && stocked ? (
        <div className="grid gap-3">
          <div className="grid gap-3 sm:grid-cols-[8rem_minmax(0,12rem)_1fr] sm:items-end">
            <LabeledField label={t("dispense.quantity")} required>
              {(id, describedBy) => (
                <Input
                  id={id}
                  ref={qtyRef}
                  value={state.qty}
                  inputMode="numeric"
                  autoComplete="off"
                  dir="ltr"
                  aria-invalid={error ? true : undefined}
                  aria-describedby={describedBy}
                  data-testid="dispense-qty"
                  onChange={(e) => {
                    onChange({ qty: e.target.value });
                  }}
                />
              )}
            </LabeledField>
            <LabeledField label={t("dispense.unit")}>
              {(id) => (
                <Select
                  value={state.unit || "__base"}
                  onValueChange={(v) => {
                    onChange({ unit: v === "__base" ? "" : v });
                  }}
                >
                  <SelectTrigger id={id} className="h-11 w-full md:h-10" data-testid="dispense-unit">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__base">{unitName}</SelectItem>
                    {dispensable.map((u) => (
                      <SelectItem key={u.unit_code} value={u.unit_code}>
                        {t("dispense.unitOf", { unit: names.name(u), factor: u.factor, base: unitName })}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </LabeledField>
            <p className="text-sm text-muted sm:pb-2.5" aria-live="polite">
              {qty !== null && state.unit ? (
                <>
                  {t("dispense.equals")} <QtyText value={qty} unit={unitName} className="text-fg" />
                </>
              ) : null}
            </p>
          </div>

          <div className="grid gap-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm font-medium">{t("dispense.batches")}</p>
              <div className="flex items-center gap-2">
                <Switch
                  id={overrideId}
                  checked={state.override}
                  disabled={line.batches.length === 0}
                  data-testid="dispense-override"
                  onCheckedChange={(v) => {
                    onChange({
                      override: v,
                      picks: v ? Object.fromEntries([...fefo].map(([id, q]) => [String(id), String(q)])) : {},
                    });
                  }}
                />
                <Label htmlFor={overrideId} className="text-sm font-normal">
                  {t("dispense.otherBatches")}
                </Label>
              </div>
            </div>
            {line.batches.length === 0 ? (
              <p className="text-sm text-danger-fg">{t("dispense.noBatches")}</p>
            ) : (
              <ul className="grid gap-2" aria-label={t("dispense.batches")}>
                {line.batches.map((bt) => {
                  const suggested = fefo.get(bt.batch_id);
                  const pickId = `pick-${String(line.id)}-${String(bt.batch_id)}`;
                  return (
                    <li
                      key={bt.batch_id}
                      className={cn(
                        "flex flex-wrap items-center gap-x-3 gap-y-1 rounded-control border px-3 py-2 text-sm",
                        suggested && !state.override ? "border-primary bg-primary-soft" : "border-border",
                      )}
                      data-testid="dispense-batch"
                      data-batch-no={bt.batch_no}
                      data-suggested={suggested ? "true" : "false"}
                    >
                      <span className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-1">
                        <bdi className="font-medium">{bt.batch_no}</bdi>
                        <span className="text-muted">
                          {t("dispense.expires")} <DateText value={bt.expiry_date} />
                        </span>
                        <ExpiryBadge daysLeft={bt.days_left} />
                        <span className="text-muted">
                          {t("dispense.onHand")} <QtyText value={bt.on_hand} unit={unitName} />
                        </span>
                        {bt.batch_id === firstUsable ? <Badge variant="soft">{t("dispense.fefo")}</Badge> : null}
                      </span>
                      {state.override ? (
                        <span className="flex items-center gap-2">
                          <Label htmlFor={pickId} className="sr-only">
                            {t("dispense.pickLabel", { batch: bt.batch_no })}
                          </Label>
                          <Input
                            id={pickId}
                            className="w-24"
                            value={state.picks[String(bt.batch_id)] ?? ""}
                            inputMode="numeric"
                            dir="ltr"
                            placeholder="0"
                            data-testid="dispense-pick"
                            onChange={(e) => {
                              onChange({ picks: { ...state.picks, [String(bt.batch_id)]: e.target.value } });
                            }}
                          />
                        </span>
                      ) : suggested ? (
                        <span className="font-medium text-primary-strong">
                          {t("dispense.suggestedTake", { qty: formatNumber(suggested, names.language) })}
                        </span>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            )}
            {state.override ? (
              <div className="grid gap-3 sm:grid-cols-2">
                <LabeledField label={t("dispense.overrideReason")} required>
                  {(id) => (
                    <Select
                      value={state.reason}
                      onValueChange={(v) => {
                        onChange({ reason: v });
                      }}
                    >
                      <SelectTrigger id={id} className="h-11 w-full md:h-10" data-testid="dispense-reason">
                        <SelectValue placeholder={t("common.chooseReason")} />
                      </SelectTrigger>
                      <SelectContent>
                        {reasons.map((r) => (
                          <SelectItem key={r.code} value={r.code}>
                            {names.label(r)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
                </LabeledField>
                <LabeledField label={t("dispense.overrideNote")}>
                  {(id) => (
                    <Input
                      id={id}
                      value={state.note}
                      maxLength={300}
                      data-testid="dispense-reason-note"
                      onChange={(e) => {
                        onChange({ note: e.target.value });
                      }}
                    />
                  )}
                </LabeledField>
              </div>
            ) : null}
          </div>

          {partial ? (
            <fieldset className="grid gap-2 rounded-control border border-warning-border bg-warning-bg p-3 text-warning-fg">
              <legend className="px-1 text-sm font-medium">
                {t("dispense.partialTitle", { rest: formatNumber(line.remaining - qty, names.language) })}
              </legend>
              <RadioGroup
                value={state.remainder}
                onValueChange={(v) => {
                  onChange({ remainder: v as Remainder });
                }}
                className="grid gap-2"
              >
                {REMAINDERS.map((r) => (
                  <div key={r} className="flex items-start gap-2">
                    <RadioGroupItem value={r} id={`rem-${String(line.id)}-${r}`} data-testid={`remainder-${r}`} />
                    <Label htmlFor={`rem-${String(line.id)}-${r}`} className="grid gap-0.5 font-normal">
                      <span className="font-medium">{t(`dispense.remainder.${r}`)}</span>
                      <span className="text-xs">{t(`dispense.remainder.${r}Hint`)}</span>
                    </Label>
                  </div>
                ))}
              </RadioGroup>
            </fieldset>
          ) : null}
          {error ? (
            <p role="alert" className="text-sm font-medium text-danger-fg" data-testid="dispense-line-error">
              {error}
            </p>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

function DispenseDone({ result, onClose }: { result: Dispense; onClose: () => void }) {
  const { t } = useTranslation(["pharmacy", "common"]);
  const names = useNames();
  return (
    <div className="grid gap-4" data-testid="dispense-done">
      <AlertCard
        variant="success"
        icon={<CheckCircle2 />}
        title={t("dispense.doneTitle", { number: result.number })}
        live
      >
        {t("dispense.doneBody")}
      </AlertCard>
      <ul className="grid gap-2 text-sm">
        {result.lines.map((ln) => (
          <li
            key={ln.id}
            className="flex flex-wrap justify-between gap-2 rounded-control border border-border px-3 py-2"
          >
            <span className="min-w-0 break-words">{names.name(ln.service)}</span>
            <span className="flex flex-wrap items-center gap-2 text-muted">
              <bdi data-testid="dispensed-batch">{ln.batch_no}</bdi>
              <span className="tabular">{formatNumber(ln.qty_base, names.language)}</span>
              {ln.batch_override ? <Badge variant="warning">{t("dispense.overridden")}</Badge> : null}
            </span>
          </li>
        ))}
      </ul>
      <DialogFooter>
        <Button onClick={onClose} data-testid="dispense-close">
          {t("common:actions.close")}
        </Button>
      </DialogFooter>
    </div>
  );
}
