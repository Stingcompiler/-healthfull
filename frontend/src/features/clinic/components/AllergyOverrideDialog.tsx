import { ShieldAlert } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { KbdCombo } from "@/components/Kbd";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useTranslateError } from "@/lib/api/translate-error";
import { useShortcut } from "@/lib/hooks/use-shortcut";
import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

import type { AllergyAlert } from "../types";

/** Mirrors the server's ALLERGY_OVERRIDE_REASON_MIN; the server enforces it. */
const REASON_MIN = 3;

/**
 * The prescribing alert (FEATURES 3.2): the order is refused until the doctor states why a
 * drug matching an allergy is given anyway; the server stores the reason with who and when.
 */
export function AllergyOverrideDialog({
  alerts,
  names,
  onCancel,
  onConfirm,
}: {
  alerts: AllergyAlert[] | null;
  names: ReadonlyMap<number, string>;
  onCancel: () => void;
  onConfirm: (reason: string) => Promise<void>;
}) {
  const { t } = useTranslation("clinic");
  const language = useLanguage();
  const translateError = useTranslateError();
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const open = alerts !== null;

  const valid = reason.trim().length >= REASON_MIN;

  const confirm = async () => {
    if (!valid) return;
    setPending(true);
    setError(null);
    try {
      await onConfirm(reason.trim());
    } catch (e) {
      setError(translateError(e));
    } finally {
      setPending(false);
    }
  };

  // Ctrl/Cmd+Enter in the reason confirms (the page's own Ctrl+Enter stays quiet behind it).
  useShortcut("mod+enter", () => void confirm(), {
    enabled: open && valid && !pending,
    allowInInputs: true,
    allowInDialogs: true,
  });

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o && !pending) onCancel();
      }}
    >
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-lg" data-testid="allergy-override-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-danger-fg">
            <ShieldAlert className="size-5" aria-hidden="true" />
            {t("override.title")}
          </DialogTitle>
          <DialogDescription>{t("override.description")}</DialogDescription>
        </DialogHeader>
        <ul className="flex flex-col gap-2" data-testid="allergy-alerts">
          {(alerts ?? []).map((a) => (
            <li
              key={`${String(a.service_id)}-${String(a.allergy_id)}`}
              className="rounded-control border border-danger-border bg-danger-bg px-3 py-2 text-sm text-danger-fg"
            >
              <span className="font-semibold">{names.get(a.service_id) ?? ""}</span>
              {" — "}
              {t("override.match", {
                allergen: pickName({ ar: a.allergen_ar, en: a.allergen }, language),
                match: t(
                  `override.matchKind.${a.match === "item" || a.match === "drug_class" ? a.match : "substance"}`,
                ),
                severity: t(`allergy.severity.${isSeverity(a.severity) ? a.severity : "moderate"}`),
              })}
            </li>
          ))}
        </ul>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="override-reason">
            {t("override.reason")}
            <span className="text-danger-fg" aria-hidden="true">
              *
            </span>
          </Label>
          <Textarea
            id="override-reason"
            value={reason}
            maxLength={1000}
            onChange={(e) => setReason(e.target.value)}
            aria-describedby="override-reason-hint"
            data-testid="override-reason"
          />
          <p id="override-reason-hint" className="text-xs text-muted">
            {t("override.reasonHint", { min: REASON_MIN })}
          </p>
        </div>
        {error ? (
          <AlertCard variant="danger" live title={t("override.error")}>
            {error}
          </AlertCard>
        ) : null}
        <DialogFooter>
          <Button variant="outline" onClick={onCancel} disabled={pending}>
            {t("override.back")}
          </Button>
          <Button
            variant="destructive"
            onClick={() => void confirm()}
            loading={pending}
            disabled={!valid}
            data-testid="override-confirm"
          >
            {t("override.confirm")}
            <KbdCombo combo="mod+enter" className="max-md:hidden" />
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

const SEVERITIES = ["mild", "moderate", "severe", "life_threatening"] as const;
function isSeverity(value: string): value is (typeof SEVERITIES)[number] {
  return (SEVERITIES as readonly string[]).includes(value);
}
