import { useId, type ReactNode } from "react";
import type { Control, FieldPath, FieldValues } from "react-hook-form";
import { useTranslation } from "react-i18next";

import { PasswordField, SwitchField, TextField } from "@/components/form";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import type { ApproverState } from "@/lib/approver";

/**
 * The one approver field set of every desk approval (ADR 0009, 0018, 0022): a colleague who
 * may approve types their own username and password into the actor's dialog; the server checks
 * the credentials, that the approver is someone else when the rule says so, and that they may
 * approve, and records them. The password is never stored.
 *
 * Two shapes, one look and one wording (`common:approver.*`):
 * - required (a second person must approve: admission in error, paid return, claims rebill):
 *   the fields always show;
 * - optional (the actor's own permission may be enough: a discount within their limit, a
 *   duplicate reference for a supervisor): a switch «يعتمد شخص آخر الآن» shows the fields.
 *
 * `SecondApproverFields` binds to react-hook-form; `ApproverFieldset` is the same set for a
 * dialog that keeps plain state.
 */
export function SecondApproverFields<T extends FieldValues>({
  control,
  usernameName,
  passwordName,
  enabledName,
  enabled = true,
  required = true,
  hint,
  testId = "second-approver",
}: {
  control: Control<T>;
  usernameName: FieldPath<T>;
  passwordName: FieldPath<T>;
  /** Optional approval: the boolean field of the switch (fields show while it is on). */
  enabledName?: FieldPath<T>;
  /** The switch's current value (from `useWatch`), when `enabledName` is given. */
  enabled?: boolean;
  /** Without a switch: whether the fields must be filled (false when the actor may approve). */
  required?: boolean;
  /** What the approver confirms, and who may approve. */
  hint?: ReactNode;
  testId?: string;
}) {
  const { t } = useTranslation("common");
  const optional = enabledName !== undefined;
  const show = !optional || enabled;
  return (
    <fieldset className="grid gap-3 rounded-control border border-border p-3" data-testid={testId}>
      <legend className="px-1 text-sm font-medium text-fg">{t("approver.title")}</legend>
      {optional ? (
        <SwitchField
          control={control}
          name={enabledName}
          label={t("approver.toggle")}
          description={hint ?? t("approver.hint")}
        />
      ) : (
        <p className="text-xs text-pretty text-muted">{hint ?? t("approver.hint")}</p>
      )}
      {show ? (
        <div className="grid gap-3 sm:grid-cols-2">
          <TextField
            control={control}
            name={usernameName}
            label={t("approver.username")}
            autoComplete="off"
            dir="ltr"
            required={optional || required}
          />
          <PasswordField
            control={control}
            name={passwordName}
            label={t("approver.password")}
            autoComplete="new-password"
            required={optional || required}
          />
        </div>
      ) : null}
    </fieldset>
  );
}

/** `SecondApproverFields` for a dialog without react-hook-form (same look, same words). */
export function ApproverFieldset({
  value,
  onChange,
  optional = true,
  hint,
  testId = "second-approver",
}: {
  value: ApproverState;
  onChange: (next: ApproverState) => void;
  optional?: boolean;
  hint?: ReactNode;
  testId?: string;
}) {
  const { t } = useTranslation("common");
  const id = useId();
  const show = !optional || value.enabled;
  return (
    <fieldset className="grid gap-3 rounded-control border border-border p-3" data-testid={testId}>
      <legend className="px-1 text-sm font-medium text-fg">{t("approver.title")}</legend>
      {optional ? (
        <div className="flex items-start gap-3">
          <Switch
            id={`${id}-switch`}
            checked={value.enabled}
            data-testid="approver-toggle"
            onCheckedChange={(enabled) => {
              onChange({ ...value, enabled });
            }}
          />
          <div className="grid gap-0.5">
            <Label htmlFor={`${id}-switch`}>{t("approver.toggle")}</Label>
            <p className="text-xs text-pretty text-muted">{hint ?? t("approver.hint")}</p>
          </div>
        </div>
      ) : (
        <p className="text-xs text-pretty text-muted">{hint ?? t("approver.hint")}</p>
      )}
      {show ? (
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="grid min-w-0 gap-1.5">
            <Label htmlFor={`${id}-user`}>
              {t("approver.username")}
              <span aria-hidden="true" className="text-danger">
                {" *"}
              </span>
            </Label>
            <Input
              id={`${id}-user`}
              value={value.username}
              autoComplete="off"
              dir="ltr"
              data-testid="approver-username"
              onChange={(e) => {
                onChange({ ...value, username: e.target.value });
              }}
            />
          </div>
          <div className="grid min-w-0 gap-1.5">
            <Label htmlFor={`${id}-password`}>
              {t("approver.password")}
              <span aria-hidden="true" className="text-danger">
                {" *"}
              </span>
            </Label>
            <Input
              id={`${id}-password`}
              type="password"
              value={value.password}
              autoComplete="new-password"
              data-testid="approver-password"
              onChange={(e) => {
                onChange({ ...value, password: e.target.value });
              }}
            />
          </div>
        </div>
      ) : null}
    </fieldset>
  );
}
