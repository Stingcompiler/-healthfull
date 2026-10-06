import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { AlertCard } from "@/components/AlertCard";
import {
  CheckboxField,
  Form,
  RadioGroupField,
  SelectField,
  SwitchField,
  TextareaField,
  TextField,
} from "@/components/form";
import { SearchInput } from "@/components/SearchInput";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { phoneSchema, requiredString, vmsg } from "@/lib/validation";

import { Demo, Section } from "../Section";

const DEPARTMENTS = ["internal", "pediatrics", "obgyn", "dental"] as const;

const schema = z.object({
  fullName: requiredString.pipe(z.string().min(5, vmsg("validation.minLength", { min: 5 }))),
  phone: phoneSchema,
  sex: z.enum(["male", "female"], vmsg("validation.selectOption")),
  department: z.enum(DEPARTMENTS, vmsg("validation.selectOption")),
  notes: z.string().max(200),
  emergency: z.boolean(),
  consent: z.boolean().refine((v) => v, vmsg("validation.mustAccept")),
});

type Values = z.input<typeof schema>;

export function FormsSection() {
  const { t } = useTranslation(["design", "common"]);
  const [submitted, setSubmitted] = useState(false);
  const [lastSearch, setLastSearch] = useState<string | null>(null);

  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      fullName: "",
      phone: "",
      sex: undefined,
      department: undefined,
      notes: "",
      emergency: false,
      consent: false,
    },
  });

  const onSubmit = form.handleSubmit(() => {
    setSubmitted(true);
  });

  return (
    <Section id="forms" title={t("sections.forms")} description={t("descriptions.forms")}>
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[3fr_2fr]">
        <Demo label={t("forms.title")}>
          <Card>
            <Form {...form}>
              <form
                onSubmit={(e) => void onSubmit(e)}
                noValidate
                className="grid gap-4 sm:grid-cols-2"
                aria-label={t("forms.title")}
              >
                <TextField
                  control={form.control}
                  name="fullName"
                  label={t("forms.fullName")}
                  placeholder={t("forms.fullNamePlaceholder")}
                  required
                  className="sm:col-span-2"
                />
                <TextField
                  control={form.control}
                  name="phone"
                  label={t("forms.phone")}
                  description={t("forms.phoneHint")}
                  type="tel"
                  inputMode="tel"
                  dir="ltr"
                  required
                />
                <SelectField
                  control={form.control}
                  name="department"
                  label={t("forms.department")}
                  placeholder={t("forms.departmentPlaceholder")}
                  options={DEPARTMENTS.map((d) => ({ value: d, label: t(`forms.departments.${d}`) }))}
                  required
                />
                <RadioGroupField
                  control={form.control}
                  name="sex"
                  label={t("forms.sex")}
                  options={[
                    { value: "male", label: t("common:sex.male") },
                    { value: "female", label: t("common:sex.female") },
                  ]}
                  required
                  className="sm:col-span-2"
                />
                <TextareaField
                  control={form.control}
                  name="notes"
                  label={t("forms.notes")}
                  placeholder={t("forms.notesPlaceholder")}
                  rows={3}
                  className="sm:col-span-2"
                />
                <SwitchField
                  control={form.control}
                  name="emergency"
                  label={t("forms.emergency")}
                  description={t("forms.emergencyHint")}
                  className="sm:col-span-2"
                />
                <CheckboxField
                  control={form.control}
                  name="consent"
                  label={t("forms.consent")}
                  required
                  className="sm:col-span-2"
                />
                {submitted ? (
                  <AlertCard variant="success" title={t("forms.submitted")} live className="sm:col-span-2" />
                ) : null}
                <div className="flex flex-wrap gap-2 sm:col-span-2">
                  <Button type="submit">{t("forms.submit")}</Button>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => {
                      setSubmitted(false);
                      void form.trigger();
                    }}
                  >
                    {t("forms.showErrors")}
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() => {
                      setSubmitted(false);
                      form.reset();
                    }}
                  >
                    {t("forms.reset")}
                  </Button>
                </div>
              </form>
            </Form>
          </Card>
        </Demo>

        <Demo label={t("forms.states")}>
          <Card className="gap-5">
            <div className="grid gap-2">
              <Label htmlFor="ds-disabled">{t("forms.disabledLabel")}</Label>
              <Input id="ds-disabled" disabled value={t("forms.disabledValue")} readOnly />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="ds-invalid" className="text-danger-fg">
                {t("forms.invalidLabel")}
              </Label>
              <Input id="ds-invalid" aria-invalid defaultValue="12ab" dir="ltr" />
              <p className="text-xs font-medium text-danger-fg">{t("common:validation.number")}</p>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="ds-search">{t("forms.searchLabel")}</Label>
              <SearchInput
                id="ds-search"
                label={t("forms.searchLabel")}
                placeholder={t("forms.searchPlaceholder")}
                onSearch={setLastSearch}
              />
              <p className="text-xs text-muted" aria-live="polite">
                {lastSearch ? t("forms.searchResult", { query: lastSearch }) : t("forms.searchNone")}
              </p>
            </div>
          </Card>
        </Demo>
      </div>
    </Section>
  );
}
