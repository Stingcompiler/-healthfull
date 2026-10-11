import type { Control, FieldPath, FieldValues } from "react-hook-form";
import { useTranslation } from "react-i18next";

import { PasswordField, TextField } from "@/components/form";

/**
 * A second person approves on the spot by typing their own username and password into the
 * actor's dialog (ADR 0009 desk approval, ADR 0018 second person). The server checks the
 * credentials, that the approver is someone else and that they may approve; the password is
 * never stored.
 */
export function SecondApproverFields<T extends FieldValues>({
  control,
  usernameName,
  passwordName,
  hint,
  testId = "second-approver",
}: {
  control: Control<T>;
  usernameName: FieldPath<T>;
  passwordName: FieldPath<T>;
  /** What the approver confirms, and who may approve. */
  hint?: string;
  testId?: string;
}) {
  const { t } = useTranslation("common");
  return (
    <fieldset className="grid gap-3 rounded-control border border-border p-3" data-testid={testId}>
      <legend className="px-1 text-sm font-medium text-fg">{t("approver.title")}</legend>
      <p className="text-xs text-pretty text-muted">{hint ?? t("approver.hint")}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <TextField
          control={control}
          name={usernameName}
          label={t("approver.username")}
          autoComplete="off"
          dir="ltr"
          required
        />
        <PasswordField
          control={control}
          name={passwordName}
          label={t("approver.password")}
          autoComplete="new-password"
          required
        />
      </div>
    </fieldset>
  );
}
