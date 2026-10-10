import { useId, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { formatNumber } from "@/lib/format";
import { cn } from "@/lib/utils";

import type { ApproverState } from "../lib/approver";
import { useNames } from "../lib/use-names";
import type { AdjustmentStatus, CountStatus, ReceiptStatus, Store, TransferStatus } from "../types";

/** A label above one control; the control gets `id` through the render prop. */
export function LabeledField({
  label,
  hint,
  error,
  required = false,
  className,
  children,
}: {
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  required?: boolean;
  className?: string;
  children: (id: string, describedBy: string | undefined) => ReactNode;
}) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const describedBy = [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(" ") || undefined;
  return (
    <div className={cn("grid min-w-0 gap-1.5", className)}>
      <Label htmlFor={id}>
        {label}
        {required ? (
          <span aria-hidden="true" className="text-danger">
            {" *"}
          </span>
        ) : null}
      </Label>
      {children(id, describedBy)}
      {hint ? (
        <p id={hintId} className="text-xs text-muted">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} role="alert" className="text-xs font-medium text-danger-fg">
          {error}
        </p>
      ) : null}
    </div>
  );
}

const ALL = "all";

/** Store choice; `allowAll` adds "All stores" (undefined). */
export function StoreSelect({
  stores,
  value,
  onChange,
  label,
  allowAll = false,
  onlyDispensing = false,
  testId,
  className,
}: {
  stores: readonly Store[];
  value: number | undefined;
  onChange: (storeId: number | undefined) => void;
  label: string;
  allowAll?: boolean;
  onlyDispensing?: boolean;
  testId?: string;
  className?: string;
}) {
  const { t } = useTranslation("pharmacy");
  const names = useNames();
  const shown = onlyDispensing ? stores.filter((s) => s.allows_dispense) : stores;
  return (
    <LabeledField label={label} className={className}>
      {(id) => (
        <Select
          value={value === undefined ? (allowAll ? ALL : "") : String(value)}
          onValueChange={(v) => {
            onChange(v === ALL ? undefined : Number(v));
          }}
        >
          <SelectTrigger id={id} className="h-11 w-full md:h-10" data-testid={testId}>
            <SelectValue placeholder={t("common.chooseStore")} />
          </SelectTrigger>
          <SelectContent>
            {allowAll ? <SelectItem value={ALL}>{t("common.allStores")}</SelectItem> : null}
            {shown.map((s) => (
              <SelectItem key={s.id} value={String(s.id)}>
                {names.name(s)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
    </LabeledField>
  );
}

const STATUS_VARIANT = {
  draft: "warning",
  open: "warning",
  sent: "info",
  posted: "success",
  approved: "success",
  received: "success",
  rejected: "neutral",
  cancelled: "neutral",
} as const;

type DocStatusProps =
  | { kind: "receipt"; status: ReceiptStatus }
  | { kind: "adjustment"; status: AdjustmentStatus }
  | { kind: "count"; status: CountStatus }
  | { kind: "transfer"; status: TransferStatus };

/** The status of a stock document (receipt, adjustment, count, transfer). */
export function DocStatusBadge(props: DocStatusProps) {
  const { t } = useTranslation("pharmacy");
  let label: string;
  switch (props.kind) {
    case "receipt":
      label = t(`status.receipt.${props.status}`);
      break;
    case "adjustment":
      label = t(`status.adjustment.${props.status}`);
      break;
    case "count":
      label = t(`status.count.${props.status}`);
      break;
    case "transfer":
      label = t(`status.transfer.${props.status}`);
      break;
  }
  return (
    <Badge variant={STATUS_VARIANT[props.status]} data-status={props.status}>
      {label}
    </Badge>
  );
}

/** A server error under a form. */
export function ErrorAlert({ message }: { message: string | null }) {
  const { t } = useTranslation("errors");
  if (!message) return null;
  return (
    <AlertCard variant="danger" title={t("title")} live>
      {message}
    </AlertCard>
  );
}

/** A quantity in base units with the unit's name: "30 tablets". */
export function QtyText({ value, unit, className }: { value: number; unit: string; className?: string }) {
  const names = useNames();
  return (
    <span className={cn("tabular whitespace-nowrap", className)}>
      <bdi>{formatNumber(value, names.language)}</bdi> {unit}
    </span>
  );
}

/**
 * A supervisor approves at the counter by typing their own credentials (ADR 0009); the
 * fields show only while "a supervisor approves" is on.
 */
export function ApproverInputs({
  value,
  onChange,
  description,
  testId,
}: {
  value: ApproverState;
  onChange: (next: ApproverState) => void;
  description: ReactNode;
  testId?: string;
}) {
  const { t } = useTranslation("pharmacy");
  const switchId = useId();
  return (
    <fieldset className="grid gap-3 rounded-control border border-border p-3" data-testid={testId}>
      <div className="flex items-start gap-3">
        <Switch
          id={switchId}
          checked={value.enabled}
          onCheckedChange={(enabled) => {
            onChange({ ...value, enabled });
          }}
        />
        <div className="grid gap-0.5">
          <Label htmlFor={switchId}>{t("approver.toggle")}</Label>
          <p className="text-xs text-muted">{description}</p>
        </div>
      </div>
      {value.enabled ? (
        <div className="grid gap-3 sm:grid-cols-2">
          <LabeledField label={t("approver.username")} required>
            {(id) => (
              <Input
                id={id}
                value={value.username}
                autoComplete="off"
                dir="ltr"
                data-testid="approver-username"
                onChange={(e) => {
                  onChange({ ...value, username: e.target.value });
                }}
              />
            )}
          </LabeledField>
          <LabeledField label={t("approver.password")} required>
            {(id) => (
              <Input
                id={id}
                type="password"
                value={value.password}
                autoComplete="new-password"
                data-testid="approver-password"
                onChange={(e) => {
                  onChange({ ...value, password: e.target.value });
                }}
              />
            )}
          </LabeledField>
        </div>
      ) : null}
    </fieldset>
  );
}

/** Days until (or since) an expiry, as a badge colored by urgency. */
export function ExpiryBadge({ daysLeft }: { daysLeft: number }) {
  const { t } = useTranslation("pharmacy");
  const variant = daysLeft < 0 ? "danger" : daysLeft <= 30 ? "warning" : daysLeft <= 90 ? "info" : "neutral";
  return (
    <Badge variant={variant} data-days-left={daysLeft}>
      {daysLeft < 0 ? t("expiry.expiredAgo", { count: -daysLeft }) : t("expiry.daysLeft", { count: daysLeft })}
    </Badge>
  );
}
