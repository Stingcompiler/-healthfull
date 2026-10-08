import type { UseFormReturn } from "react-hook-form";
import { useTranslation } from "react-i18next";
import {
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
  RadioGroupField,
  TextareaField,
  TextField,
} from "@/components/form";
import { Input } from "@/components/ui/input";

import type { PatientFormValues } from "../patient-form";

export interface PatientFormFieldsProps {
  form: UseFormReturn<PatientFormValues>;
  /** Allow "unknown" sex (editing an unidentified emergency file). */
  allowUnknownSex?: boolean;
}

/** The demographic fields of FEATURES 1.1, laid out in one column on phones and two from sm. */
export function PatientFormFields({ form, allowUnknownSex = false }: PatientFormFieldsProps) {
  const { t } = useTranslation(["patients", "common"]);
  const dobMode = form.watch("dob_mode");
  const sexOptions = [
    { value: "male", label: t("common:sex.male") },
    { value: "female", label: t("common:sex.female") },
    ...(allowUnknownSex ? [{ value: "unknown", label: t("common:sex.unknown") }] : []),
  ];

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <TextField control={form.control} name="full_name_ar" label={t("form.nameAr")} dir="rtl" autoComplete="off" />
      <TextField control={form.control} name="full_name_en" label={t("form.nameEn")} dir="ltr" autoComplete="off" />
      <RadioGroupField control={form.control} name="sex" label={t("form.sex")} options={sexOptions} required />
      <RadioGroupField
        control={form.control}
        name="dob_mode"
        label={t("form.birthKnown")}
        options={[
          { value: "date", label: t("form.byDate") },
          { value: "age", label: t("form.byAge") },
        ]}
      />
      {dobMode === "date" ? (
        <FormField
          control={form.control}
          name="date_of_birth"
          render={({ field }) => (
            <FormItem>
              <FormLabel>{t("form.dateOfBirth")}</FormLabel>
              <FormControl>
                <Input type="date" dir="ltr" max="9999-12-31" {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
      ) : (
        <TextField
          control={form.control}
          name="age_years"
          label={t("form.ageYears")}
          inputMode="numeric"
          dir="ltr"
          maxLength={3}
        />
      )}
      <TextField
        control={form.control}
        name="phone"
        label={t("form.phone")}
        type="tel"
        inputMode="tel"
        dir="ltr"
        autoComplete="off"
      />
      <TextField control={form.control} name="phone_alt" label={t("form.phoneAlt")} type="tel" dir="ltr" />
      <TextField control={form.control} name="national_id" label={t("form.nationalId")} dir="ltr" />
      <TextField control={form.control} name="address" label={t("form.address")} className="sm:col-span-2" />
      <TextField control={form.control} name="emergency_contact_name" label={t("form.emergencyName")} />
      <TextField
        control={form.control}
        name="emergency_contact_phone"
        label={t("form.emergencyPhone")}
        type="tel"
        dir="ltr"
      />
      <TextareaField control={form.control} name="notes" label={t("form.notes")} rows={2} className="sm:col-span-2" />
    </div>
  );
}
