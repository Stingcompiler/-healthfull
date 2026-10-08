import type { ReactNode } from "react";
import type { FieldValues, UseFormReturn } from "react-hook-form";
import { useTranslation } from "react-i18next";

import { AlertCard } from "@/components/AlertCard";
import { Form } from "@/components/form";
import { Badge } from "@/components/ui/badge";
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
import { cn } from "@/lib/utils";

export interface FormDialogProps<T extends FieldValues> {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  form: UseFormReturn<T>;
  onSubmit: (values: T) => Promise<void>;
  /** The last server error of the submit, shown above the fields. */
  error?: unknown;
  submitLabel?: ReactNode;
  destructive?: boolean;
  wide?: boolean;
  children: ReactNode;
}

/** A dialog holding one react-hook-form form (create and edit screens). */
export function FormDialog<T extends FieldValues>({
  open,
  onOpenChange,
  title,
  description,
  form,
  onSubmit,
  error,
  submitLabel,
  destructive,
  wide,
  children,
}: FormDialogProps<T>) {
  const { t } = useTranslation(["common", "errors"]);
  const translateError = useTranslateError();
  const submit = form.handleSubmit(onSubmit);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={cn(wide && "md:max-w-2xl")}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description ? <DialogDescription>{description}</DialogDescription> : null}
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={(e) => void submit(e)} noValidate className="grid min-w-0 gap-4">
            {error ? (
              <AlertCard variant="danger" title={t("errors:title")} live>
                {translateError(error)}
              </AlertCard>
            ) : null}
            {children}
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  onOpenChange(false);
                }}
              >
                {t("actions.cancel")}
              </Button>
              <Button
                type="submit"
                variant={destructive ? "destructive" : "default"}
                loading={form.formState.isSubmitting}
              >
                {submitLabel ?? t("actions.save")}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}

/** Active / inactive badge. */
export function ActiveBadge({ active }: { active: boolean }) {
  const { t } = useTranslation("admin");
  return <Badge variant={active ? "success" : "neutral"}>{active ? t("common.active") : t("common.inactive")}</Badge>;
}

/** A code, number or ID shown on its own: isolated and left-to-right. */
export function Code({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <bdi dir="ltr" className={cn("font-mono text-xs text-fg-muted", className)}>
      {children}
    </bdi>
  );
}
