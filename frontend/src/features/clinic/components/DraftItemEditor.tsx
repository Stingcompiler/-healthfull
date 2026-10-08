import { Calculator, ShieldAlert, X } from "lucide-react";
import { useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useTranslateError } from "@/lib/api/translate-error";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

import { useFrequencies, usePrescriptionPreview } from "../api";
import type { DraftItem, DraftRx } from "../draft";
import { KIND_ICONS } from "../kind-icons";
import type { AllergyAlert, PrescriptionPreviewInput, Route } from "../types";

const ROUTES: readonly Route[] = [
  "oral",
  "iv",
  "im",
  "sc",
  "topical",
  "inhaled",
  "rectal",
  "ophthalmic",
  "otic",
  "nasal",
  "other",
];

/** One item of the order being written; drugs get the prescription builder (FEATURES 3.5). */
export function DraftItemEditor({
  item,
  onChange,
  onRemove,
  allergyMatches = [],
}: {
  item: DraftItem;
  onChange: (next: DraftItem) => void;
  onRemove: () => void;
  /** Active allergies this drug matches: the card turns red and names them. */
  allergyMatches?: readonly AllergyAlert[];
}) {
  const { t } = useTranslation("clinic");
  const language = useLanguage();
  const Icon = KIND_ICONS[item.kind];
  const name = pickName({ ar: item.nameAr, en: item.nameEn }, language);
  const idBase = `draft-${item.key}`;
  const highlighted = allergyMatches.length > 0;
  const allergens = [...new Set(allergyMatches.map((a) => pickName({ ar: a.allergen_ar, en: a.allergen }, language)))];

  return (
    <li
      className={
        highlighted
          ? "flex flex-col gap-3 rounded-control border border-danger-border bg-danger-bg p-3"
          : "flex flex-col gap-3 rounded-control border border-border bg-surface p-3"
      }
      data-testid="draft-item"
      data-service-code={item.code}
      data-allergy={highlighted ? "true" : undefined}
    >
      <div className="flex min-w-0 items-start gap-2">
        <Icon className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold break-words text-fg">{name}</div>
          <div className="text-xs text-muted">
            <bdi>{item.code}</bdi>
            {" · "}
            {t(`kind.${item.kind}`)}
          </div>
          {highlighted ? (
            <p
              className="mt-1 flex items-start gap-1.5 text-xs font-semibold text-danger-fg"
              data-testid="draft-allergy"
            >
              <ShieldAlert className="mt-px size-3.5 shrink-0" aria-hidden="true" />
              <span className="min-w-0 break-words">
                {t("orders.allergyMatch", { allergens: allergens.join(language === "ar" ? "، " : ", ") })}
              </span>
            </p>
          ) : null}
        </div>
        <Button size="icon-sm" variant="ghost" onClick={onRemove} aria-label={t("orders.removeItem", { name })}>
          <X aria-hidden="true" />
        </Button>
      </div>
      {item.rx ? (
        <PrescriptionFields item={item} rx={item.rx} idBase={idBase} onChange={onChange} />
      ) : (
        <div className="grid gap-3 sm:grid-cols-[8rem_minmax(0,1fr)]">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`${idBase}-qty`} className="text-xs">
              {t("orders.quantity")}
            </Label>
            <Input
              id={`${idBase}-qty`}
              inputMode="numeric"
              dir="ltr"
              value={item.quantity}
              onChange={(e) => onChange({ ...item, quantity: e.target.value })}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`${idBase}-note`} className="text-xs">
              {t("orders.note")}
            </Label>
            <Input
              id={`${idBase}-note`}
              value={item.note}
              maxLength={500}
              onChange={(e) => onChange({ ...item, note: e.target.value })}
            />
          </div>
        </div>
      )}
    </li>
  );
}

function PrescriptionFields({
  item,
  rx,
  idBase,
  onChange,
}: {
  item: DraftItem;
  rx: DraftRx;
  idBase: string;
  onChange: (next: DraftItem) => void;
}) {
  const { t } = useTranslation("clinic");
  const language = useLanguage();
  const frequencies = useFrequencies();
  const translateError = useTranslateError();
  const setRx = (patch: Partial<DraftRx>) => onChange({ ...item, rx: { ...rx, ...patch } });
  const unit = pickName({ ar: item.unitAr, en: item.unitEn }, language);
  const frequencyLabel = rx.frequencyCode ? t(`frequency.${rx.frequencyCode}`, { defaultValue: rx.frequencyCode }) : "";

  // Debounce a string (a new object every render would never settle).
  const key = useDebouncedValue(
    JSON.stringify({
      dose_quantity: rx.doseQuantity.trim() || null,
      frequency_code: rx.frequencyCode,
      duration_days: Number(rx.durationDays) > 0 ? Number(rx.durationDays) : null,
      as_needed: rx.asNeeded,
    }),
    250,
  );
  const input = useMemo(() => JSON.parse(key) as PrescriptionPreviewInput, [key]);
  const canPreview = Boolean(input.dose_quantity) && Boolean(input.frequency_code);
  const preview = usePrescriptionPreview(input, canPreview);
  const computed = canPreview && preview.data ? preview.data.quantity : null;

  // Keep the computed quantity on the draft (favorites and the summary line use it).
  useEffect(() => {
    if (computed !== item.computedQuantity) onChange({ ...item, computedQuantity: computed });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [computed]);

  return (
    <div className="flex flex-col gap-3" data-testid="rx-builder">
      {/* Sized by the card (container), not the viewport: the tab sits beside the summary. */}
      <div className="grid grid-cols-2 gap-3 @xl:grid-cols-[6rem_minmax(0,2fr)_5rem_minmax(0,1.5fr)]">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${idBase}-dose`} className="text-xs">
            {unit ? t("rx.doseIn", { unit }) : t("rx.dose")}
          </Label>
          <Input
            id={`${idBase}-dose`}
            inputMode="decimal"
            dir="ltr"
            value={rx.doseQuantity}
            onChange={(e) => setRx({ doseQuantity: e.target.value })}
            data-testid="rx-dose"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${idBase}-freq`} className="text-xs">
            {t("rx.frequency")}
          </Label>
          <Select value={rx.frequencyCode} onValueChange={(v) => setRx({ frequencyCode: v })}>
            <SelectTrigger
              id={`${idBase}-freq`}
              data-testid="rx-frequency"
              title={rx.frequencyCode ? frequencyLabel : undefined}
            >
              {/* A narrow card shows the code (the label stays for screen readers); a wide one both. */}
              <SelectValue placeholder={t("rx.chooseFrequency")}>
                {rx.frequencyCode ? (
                  <span className="min-w-0 truncate">
                    <bdi className="tabular font-semibold">{rx.frequencyCode}</bdi>
                    <span className="@max-xl:sr-only"> · {frequencyLabel}</span>
                  </span>
                ) : undefined}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              {(frequencies.data ?? []).map((f) => (
                <SelectItem key={f.code} value={f.code} data-testid={`rx-frequency-${f.code}`}>
                  <bdi className="tabular font-semibold">{f.code}</bdi> ·{" "}
                  {t(`frequency.${f.code}`, { defaultValue: f.code })}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${idBase}-days`} className="text-xs">
            {t("rx.duration")}
          </Label>
          <Input
            id={`${idBase}-days`}
            inputMode="numeric"
            dir="ltr"
            value={rx.durationDays}
            onChange={(e) => setRx({ durationDays: e.target.value })}
            data-testid="rx-days"
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${idBase}-route`} className="text-xs">
            {t("rx.route")}
          </Label>
          <Select value={rx.route} onValueChange={(v) => setRx({ route: v as Route })}>
            <SelectTrigger id={`${idBase}-route`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {ROUTES.map((r) => (
                <SelectItem key={r} value={r}>
                  {t(`route.${r}`)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_10rem]">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${idBase}-instr`} className="text-xs">
            {t("rx.instructions")}
          </Label>
          <Input
            id={`${idBase}-instr`}
            value={rx.instructions}
            maxLength={500}
            onChange={(e) => setRx({ instructions: e.target.value })}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${idBase}-qty`} className="text-xs">
            {t("rx.quantityOverride")}
          </Label>
          <Input
            id={`${idBase}-qty`}
            inputMode="numeric"
            dir="ltr"
            placeholder={computed !== null ? String(computed) : ""}
            value={item.quantity}
            onChange={(e) => onChange({ ...item, quantity: e.target.value })}
          />
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm">
          <Checkbox checked={rx.asNeeded} onCheckedChange={(v) => setRx({ asNeeded: v === true })} />
          {t("rx.asNeeded")}
        </label>
        <div className="ms-auto flex items-center gap-2 text-sm" aria-live="polite" data-testid="rx-quantity">
          <Calculator className="size-4 text-muted" aria-hidden="true" />
          {preview.isError && canPreview ? (
            <span className="text-danger-fg">{translateError(preview.error)}</span>
          ) : item.quantity.trim() ? (
            <Badge variant="soft">
              {t(unit ? "rx.quantityGiven" : "rx.quantityGivenNoUnit", { count: Number(item.quantity) || 0, unit })}
            </Badge>
          ) : computed !== null ? (
            <Badge variant="soft">
              {t(unit ? "rx.quantityComputed" : "rx.quantityComputedNoUnit", { count: computed, unit })}
            </Badge>
          ) : (
            <span className="text-muted">{t("rx.quantityNeeded")}</span>
          )}
        </div>
      </div>
    </div>
  );
}
