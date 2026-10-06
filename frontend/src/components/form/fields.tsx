import { Eye, EyeOff } from "lucide-react";
import { useId, useState, type HTMLAttributes, type ReactNode } from "react";
import type { Control, FieldPath, FieldValues } from "react-hook-form";
import { useTranslation } from "react-i18next";

import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

import { FormControl, FormDescription, FormField, FormItem, FormLabel, FormMessage } from "./form";

/*
 * Ready-made fields for the common cases. Each takes the form's `control`
 * so `name` is type-checked against the zod schema's inferred values.
 */
interface BaseFieldProps<T extends FieldValues> {
  control: Control<T>;
  name: FieldPath<T>;
  label: ReactNode;
  description?: ReactNode;
  required?: boolean;
  disabled?: boolean;
  className?: string;
}

export interface TextFieldProps<T extends FieldValues> extends BaseFieldProps<T> {
  type?: "text" | "email" | "tel" | "number" | "search" | "url";
  placeholder?: string;
  autoComplete?: string;
  inputMode?: HTMLAttributes<HTMLInputElement>["inputMode"];
  /** Force LTR for codes, phones and usernames inside RTL pages. */
  dir?: "ltr" | "rtl" | "auto";
  autoFocus?: boolean;
  maxLength?: number;
}

export function TextField<T extends FieldValues>({
  control,
  name,
  label,
  description,
  required,
  disabled,
  className,
  type = "text",
  ...inputProps
}: TextFieldProps<T>) {
  return (
    <FormField
      control={control}
      name={name}
      render={({ field }) => (
        <FormItem className={className}>
          <FormLabel required={required}>{label}</FormLabel>
          <FormControl>
            <Input type={type} disabled={disabled} {...inputProps} {...field} value={field.value ?? ""} />
          </FormControl>
          {description ? <FormDescription>{description}</FormDescription> : null}
          <FormMessage />
        </FormItem>
      )}
    />
  );
}

export interface PasswordFieldProps<T extends FieldValues> extends BaseFieldProps<T> {
  autoComplete?: "current-password" | "new-password";
  autoFocus?: boolean;
}

export function PasswordField<T extends FieldValues>({
  control,
  name,
  label,
  description,
  required,
  disabled,
  className,
  autoComplete = "current-password",
  autoFocus,
}: PasswordFieldProps<T>) {
  const { t } = useTranslation();
  const [visible, setVisible] = useState(false);
  return (
    <FormField
      control={control}
      name={name}
      render={({ field }) => (
        <FormItem className={className}>
          <FormLabel required={required}>{label}</FormLabel>
          {/* Passwords are always LTR; the wrapper shares that direction so the
              toggle sits at the input's inline end in Arabic pages too. */}
          <div className="relative" dir="ltr">
            <FormControl>
              <Input
                type={visible ? "text" : "password"}
                autoComplete={autoComplete}
                autoFocus={autoFocus}
                disabled={disabled}
                className="pe-11"
                {...field}
                value={field.value ?? ""}
              />
            </FormControl>
            <button
              type="button"
              onClick={() => {
                setVisible((v) => !v);
              }}
              aria-pressed={visible}
              className="absolute inset-y-0 end-0 flex w-10 items-center justify-center rounded-e-control text-muted hover:text-fg focus-visible:ring-3 focus-visible:ring-ring/35 focus-visible:outline-none"
            >
              {visible ? (
                <EyeOff className="size-4" aria-hidden="true" />
              ) : (
                <Eye className="size-4" aria-hidden="true" />
              )}
              <span className="sr-only">{visible ? t("actions.hidePassword") : t("actions.showPassword")}</span>
            </button>
          </div>
          {description ? <FormDescription>{description}</FormDescription> : null}
          <FormMessage />
        </FormItem>
      )}
    />
  );
}

export interface FieldOption {
  value: string;
  label: ReactNode;
  disabled?: boolean;
}

export interface SelectFieldProps<T extends FieldValues> extends BaseFieldProps<T> {
  options: readonly FieldOption[];
  placeholder?: string;
}

export function SelectField<T extends FieldValues>({
  control,
  name,
  label,
  description,
  required,
  disabled,
  className,
  options,
  placeholder,
}: SelectFieldProps<T>) {
  return (
    <FormField
      control={control}
      name={name}
      render={({ field }) => (
        <FormItem className={className}>
          <FormLabel required={required}>{label}</FormLabel>
          <Select value={field.value ?? ""} onValueChange={field.onChange} disabled={disabled} name={field.name}>
            <FormControl>
              <SelectTrigger ref={field.ref} onBlur={field.onBlur}>
                <SelectValue placeholder={placeholder} />
              </SelectTrigger>
            </FormControl>
            <SelectContent>
              {options.map((o) => (
                <SelectItem key={o.value} value={o.value} disabled={o.disabled}>
                  {o.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {description ? <FormDescription>{description}</FormDescription> : null}
          <FormMessage />
        </FormItem>
      )}
    />
  );
}

export interface TextareaFieldProps<T extends FieldValues> extends BaseFieldProps<T> {
  placeholder?: string;
  rows?: number;
  maxLength?: number;
}

export function TextareaField<T extends FieldValues>({
  control,
  name,
  label,
  description,
  required,
  disabled,
  className,
  ...textareaProps
}: TextareaFieldProps<T>) {
  return (
    <FormField
      control={control}
      name={name}
      render={({ field }) => (
        <FormItem className={className}>
          <FormLabel required={required}>{label}</FormLabel>
          <FormControl>
            <Textarea disabled={disabled} {...textareaProps} {...field} value={field.value ?? ""} />
          </FormControl>
          {description ? <FormDescription>{description}</FormDescription> : null}
          <FormMessage />
        </FormItem>
      )}
    />
  );
}

export function CheckboxField<T extends FieldValues>({
  control,
  name,
  label,
  description,
  required,
  disabled,
  className,
}: BaseFieldProps<T>) {
  return (
    <FormField
      control={control}
      name={name}
      render={({ field }) => (
        <FormItem className={cn("flex flex-row items-start gap-3", className)}>
          <FormControl>
            <Checkbox
              checked={field.value === true}
              onCheckedChange={(checked) => {
                field.onChange(checked === true);
              }}
              onBlur={field.onBlur}
              ref={field.ref}
              disabled={disabled}
              className="mt-0.5"
            />
          </FormControl>
          <div className="grid gap-1.5">
            <FormLabel required={required} className="leading-snug font-normal">
              {label}
            </FormLabel>
            {description ? <FormDescription>{description}</FormDescription> : null}
            <FormMessage />
          </div>
        </FormItem>
      )}
    />
  );
}

export function SwitchField<T extends FieldValues>({
  control,
  name,
  label,
  description,
  disabled,
  className,
}: BaseFieldProps<T>) {
  return (
    <FormField
      control={control}
      name={name}
      render={({ field }) => (
        <FormItem
          className={cn(
            "flex flex-row items-center justify-between gap-4 rounded-control border border-border p-3",
            className,
          )}
        >
          <div className="grid gap-1">
            <FormLabel>{label}</FormLabel>
            {description ? <FormDescription>{description}</FormDescription> : null}
          </div>
          <FormControl>
            <Switch
              checked={field.value === true}
              onCheckedChange={field.onChange}
              onBlur={field.onBlur}
              ref={field.ref}
              disabled={disabled}
            />
          </FormControl>
        </FormItem>
      )}
    />
  );
}

export interface RadioGroupFieldProps<T extends FieldValues> extends BaseFieldProps<T> {
  options: readonly FieldOption[];
  orientation?: "horizontal" | "vertical";
}

export function RadioGroupField<T extends FieldValues>({
  control,
  name,
  label,
  description,
  required,
  disabled,
  className,
  options,
  orientation = "horizontal",
}: RadioGroupFieldProps<T>) {
  const idPrefix = useId();
  return (
    <FormField
      control={control}
      name={name}
      render={({ field }) => (
        <FormItem className={className}>
          <FormLabel required={required}>{label}</FormLabel>
          <FormControl>
            <RadioGroup
              value={field.value ?? ""}
              onValueChange={field.onChange}
              disabled={disabled}
              orientation={orientation}
              className={cn(orientation === "horizontal" ? "flex flex-wrap gap-x-5 gap-y-2" : "grid gap-2")}
            >
              {options.map((o) => {
                const id = `${idPrefix}-${o.value}`;
                return (
                  <div key={o.value} className="flex items-center gap-2">
                    <RadioGroupItem value={o.value} id={id} disabled={o.disabled} />
                    <label htmlFor={id} className="text-sm text-fg">
                      {o.label}
                    </label>
                  </div>
                );
              })}
            </RadioGroup>
          </FormControl>
          {description ? <FormDescription>{description}</FormDescription> : null}
          <FormMessage />
        </FormItem>
      )}
    />
  );
}
