import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { AlertCard } from "@/components/AlertCard";
import { Form, SelectField, TextareaField } from "@/components/form";
import { MoneyText } from "@/components/MoneyText";
import { SecondApproverFields } from "@/components/SecondApproverFields";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useTranslateError } from "@/lib/api/translate-error";
import { vmsg } from "@/lib/validation";

import { useResolveRejection } from "../api";
import { useClaimNames } from "../lib/names";
import type { ClaimLine, ClaimReason } from "../types";

export type Resolution = "rebilled" | "written_off";

function schemaFor(secondApprover: boolean) {
  const credential = secondApprover ? z.string().trim().min(1, vmsg("validation.required")) : z.string();
  return z.object({
    reason: z.string().min(1, vmsg("validation.selectOption")),
    note: z.string().trim().max(500),
    username: credential,
    password: secondApprover ? z.string().min(1, vmsg("validation.required")) : z.string(),
  });
}

type Values = z.infer<ReturnType<typeof schemaFor>>;

interface ResolveDialogProps {
  claimId: number;
  target: { line: ClaimLine; resolution: Resolution } | null;
  reasons: readonly ClaimReason[];
  /** The center's policy: a second person approves rebills and write-offs (ADR 0018). */
  secondApprover: boolean;
  onOpenChange: (open: boolean) => void;
}

/** Mounted only while open, so every resolution starts from a fresh form. */
export function ResolveDialog(props: ResolveDialogProps) {
  return props.target ? <ResolveDialogOpen {...props} target={props.target} /> : null;
}

/**
 * Rebill a rejected amount to the patient or write it off (FEATURES 11.5), with a reason and,
 * while the center's policy asks for it, a second person's credentials (ADR 0018). The server
 * records the recorder, the approver and the time (invariant 4).
 */
function ResolveDialogOpen({
  claimId,
  target,
  reasons,
  secondApprover,
  onOpenChange,
}: ResolveDialogProps & { target: { line: ClaimLine; resolution: Resolution } }) {
  const { t } = useTranslation(["claims", "common", "errors"]);
  const translateError = useTranslateError();
  const names = useClaimNames();
  const resolve = useResolveRejection();
  const [error, setError] = useState<string | null>(null);
  const rebill = target.resolution === "rebilled";
  const form = useForm<Values>({
    resolver: zodResolver(schemaFor(secondApprover)),
    defaultValues: { reason: "", note: "", username: "", password: "" },
  });

  const submit = form.handleSubmit(async (v) => {
    setError(null);
    try {
      await resolve.mutateAsync({
        claimId,
        lineId: target.line.id,
        body: {
          resolution: target.resolution,
          reason: v.reason,
          note: v.note.trim(),
          approver: secondApprover ? { username: v.username.trim(), password: v.password } : null,
        },
      });
      onOpenChange(false);
    } catch (e) {
      setError(translateError(e));
    }
  });

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent data-testid="resolve-dialog">
        <DialogHeader>
          <DialogTitle>{rebill ? t("resolve.rebillTitle") : t("resolve.writeOffTitle")}</DialogTitle>
          <DialogDescription>
            {rebill ? t("resolve.rebillDescription") : t("resolve.writeOffDescription")}
          </DialogDescription>
        </DialogHeader>
        <p className="flex flex-wrap items-center justify-between gap-2 rounded-control bg-subtle px-3 py-2 text-sm">
          <span className="min-w-0">
            {names.text(target.line.description_ar, target.line.description_en)} · {names.person(target.line.patient)}
          </span>
          <MoneyText value={target.line.unresolved_rejection} />
        </p>
        <Form {...form}>
          <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4">
            <SelectField
              control={form.control}
              name="reason"
              label={t("resolve.reason")}
              required
              options={reasons.map((r) => ({ value: r.code, label: names.label(r) }))}
            />
            <TextareaField control={form.control} name="note" label={t("resolve.note")} />
            {secondApprover ? (
              <SecondApproverFields
                control={form.control}
                usernameName="username"
                passwordName="password"
                hint={t("resolve.approverHint")}
              />
            ) : null}
            {error ? (
              <AlertCard variant="danger" title={t("errors:title")} live>
                {error}
              </AlertCard>
            ) : null}
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  onOpenChange(false);
                }}
              >
                {t("common:actions.cancel")}
              </Button>
              <Button
                type="submit"
                variant={rebill ? "default" : "destructive"}
                loading={form.formState.isSubmitting}
                data-testid="resolve-confirm"
              >
                {rebill ? t("detail.rebill") : t("detail.writeOff")}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
