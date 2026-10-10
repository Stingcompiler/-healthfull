import { Save, TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { UnsavedChangesGuard } from "@/components/UnsavedChangesGuard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useTranslateError } from "@/lib/api/translate-error";
import { cn } from "@/lib/utils";

import { useEnterResults } from "../api";
import { isCritical, isNumber, normalizeNumber, posNeg, previewFlag, rangeText } from "../lib/flags";
import { useLabNames } from "../lib/use-lab-names";
import type { EntryParameter, LabResult } from "../types";
import { FlagBadge } from "./badges";

const POS_NEG = ["negative", "positive"] as const;

function initialValues(result: LabResult): Record<string, string> {
  const draft = result.versions.find((v) => v.status === "draft");
  const out: Record<string, string> = {};
  for (const p of result.parameters) out[p.code] = "";
  for (const v of draft?.values ?? []) out[v.parameter_code] = v.value;
  return out;
}

function initialComment(result: LabResult): string {
  return result.versions.find((v) => v.status === "draft")?.comment ?? "";
}

/**
 * Result entry per parameter (FEATURES 9.3). Each field shows the patient's reference range
 * and previews the flag while typing; the server decides the stored flag when values are saved.
 * Mounted with a key per draft revision, so a save or a new version starts from the server.
 */
export function ResultEntryForm({
  result,
  onDirtyChange,
}: {
  result: LabResult;
  onDirtyChange?: (d: boolean) => void;
}) {
  const { t } = useTranslation(["lab", "common", "errors"]);
  const translateError = useTranslateError();
  const names = useLabNames();
  const save = useEnterResults(result.line.id);
  const initial = useMemo(() => initialValues(result), [result]);
  const [values, setValues] = useState<Record<string, string>>(initial);
  const [comment, setComment] = useState(() => initialComment(result));
  const [submitted, setSubmitted] = useState(false);

  const changed = Object.keys(values).filter((code) => values[code] !== initial[code]);
  const commentChanged = comment !== initialComment(result);
  const dirty = changed.length > 0 || commentChanged;

  const invalid = (p: EntryParameter): boolean => {
    const raw = values[p.code] ?? "";
    return p.value_type === "numeric" && raw.trim() !== "" && !isNumber(raw);
  };
  const anyInvalid = result.parameters.some(invalid);
  const criticalNow = result.parameters.filter((p) =>
    isCritical(previewFlag(values[p.code] ?? "", p.value_type, p.range)),
  );

  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);

  const set = (code: string, value: string) => {
    setValues((prev) => ({ ...prev, [code]: value }));
  };

  const submit = () => {
    setSubmitted(true);
    if (anyInvalid) return;
    const payload: Record<string, string> = {};
    for (const code of changed) {
      const p = result.parameters.find((x) => x.code === code);
      const raw = (values[code] ?? "").trim();
      if (!p || raw === "") continue;
      payload[code] = p.value_type === "numeric" ? normalizeNumber(raw) : raw;
    }
    save.mutate({ values: payload, comment: commentChanged ? comment.trim() : null });
  };

  return (
    <form
      className="flex min-w-0 flex-col gap-4"
      noValidate
      data-testid="result-entry"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <UnsavedChangesGuard when={dirty && !save.isPending} />
      <ul className="flex flex-col divide-y divide-border rounded-card border border-border">
        {result.parameters.map((p) => {
          const raw = values[p.code] ?? "";
          const flag = previewFlag(raw, p.value_type, p.range);
          const bad = invalid(p) && (submitted || raw.length > 0);
          const id = `param-${p.code}`;
          const normal = p.range ? p.range.normal_text : "";
          const word = posNeg(normal);
          const reference = p.range ? rangeText(p.range.low, p.range.high, word ? t(`entry.${word}`) : normal) : "";
          return (
            <li
              key={p.code}
              className={cn(
                "grid gap-2 p-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,12rem)_auto] sm:items-center",
                isCritical(flag) && "bg-danger-bg/40",
              )}
              data-testid="result-param"
              data-code={p.code}
            >
              <div className="flex min-w-0 flex-col">
                <Label htmlFor={id} className="font-medium">
                  {names.text(p.name_ar, p.name_en)}
                  {p.unit ? (
                    <span className="ms-1 text-xs font-normal text-muted">
                      <bdi dir="ltr">({p.unit})</bdi>
                    </span>
                  ) : null}
                </Label>
                {reference ? (
                  <span className="text-xs text-muted">
                    {t("entry.reference")}: <bdi dir="ltr">{reference}</bdi>
                  </span>
                ) : null}
              </div>
              {p.value_type === "numeric" || p.value_type === "text" ? (
                <Input
                  id={id}
                  value={raw}
                  dir="ltr"
                  inputMode={p.value_type === "numeric" ? "decimal" : undefined}
                  autoComplete="off"
                  aria-invalid={bad || undefined}
                  aria-describedby={bad ? `${id}-error` : undefined}
                  className="text-start tabular"
                  onChange={(e) => {
                    set(p.code, e.target.value);
                  }}
                  data-testid={`value-${p.code}`}
                />
              ) : (
                <Select
                  value={raw}
                  onValueChange={(v) => {
                    set(p.code, v);
                  }}
                >
                  <SelectTrigger id={id} data-testid={`value-${p.code}`}>
                    <SelectValue placeholder={t("entry.choose")} />
                  </SelectTrigger>
                  <SelectContent>
                    {(p.value_type === "pos_neg" ? POS_NEG : p.choices).map((c) => (
                      <SelectItem key={c} value={c}>
                        {p.value_type === "pos_neg" ? t(`entry.${c as (typeof POS_NEG)[number]}`) : c}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
              <div className="flex min-h-6 items-center sm:justify-end" aria-live="polite">
                {flag && flag !== "none" ? <FlagBadge flag={flag} /> : null}
              </div>
              {bad ? (
                <p id={`${id}-error`} className="text-xs text-danger-fg sm:col-span-3">
                  {t("entry.notANumber")}
                </p>
              ) : null}
            </li>
          );
        })}
      </ul>
      <div className="grid gap-1.5">
        <Label htmlFor="result-comment">{t("entry.comment")}</Label>
        <Textarea
          id="result-comment"
          rows={2}
          maxLength={2000}
          value={comment}
          onChange={(e) => {
            setComment(e.target.value);
          }}
        />
      </div>
      {criticalNow.length > 0 ? (
        <AlertCard variant="danger" title={t("entry.criticalTitle")} icon={<TriangleAlert />}>
          {t("entry.criticalBody", {
            names: names.list(criticalNow.map((p) => names.text(p.name_ar, p.name_en))),
          })}
        </AlertCard>
      ) : null}
      {save.isError ? (
        <AlertCard variant="danger" title={t("errors:title")} live>
          {translateError(save.error)}
        </AlertCard>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" loading={save.isPending} disabled={!dirty} data-testid="save-results">
          <Save aria-hidden="true" />
          {t("entry.save")}
        </Button>
        {dirty ? <span className="text-xs text-muted">{t("entry.unsaved")}</span> : null}
      </div>
    </form>
  );
}
