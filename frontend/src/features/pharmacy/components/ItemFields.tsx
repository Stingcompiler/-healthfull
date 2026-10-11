import type { Control } from "react-hook-form";
import { useTranslation } from "react-i18next";

import { SelectField, SwitchField, TextField } from "@/components/form";

import { DOSAGE_FORMS, STORAGE_CODES } from "../lib/constants";
import type { ItemFieldValues } from "../lib/schemas";

/** The editable item fields, shared by the new-item dialog and the item page. */
export function ItemFields({ control }: { control: Control<ItemFieldValues> }) {
  const { t } = useTranslation("pharmacy");
  return (
    <>
      <div className="grid gap-3 sm:grid-cols-2">
        <TextField control={control} name="generic_name" label={t("items.fields.genericName")} required />
        <TextField control={control} name="generic_name_ar" label={t("items.fields.genericNameAr")} dir="rtl" />
        <TextField control={control} name="brand_name" label={t("items.fields.brandName")} />
        <SelectField
          control={control}
          name="form"
          label={t("items.fields.form")}
          options={DOSAGE_FORMS.map((f) => ({ value: f, label: t(`forms.${f}`) }))}
          required
        />
        <TextField control={control} name="strength" label={t("items.fields.strength")} />
        <TextField control={control} name="base_unit_name_ar" label={t("items.fields.baseUnitAr")} dir="rtl" required />
        <TextField control={control} name="base_unit_name_en" label={t("items.fields.baseUnitEn")} dir="ltr" required />
        <TextField control={control} name="barcode" label={t("items.fields.barcode")} dir="ltr" />
        <SelectField
          control={control}
          name="storage"
          label={t("items.fields.storage")}
          options={STORAGE_CODES.map((s) => ({ value: s, label: t(`storage.${s}`) }))}
          required
        />
        <TextField
          control={control}
          name="min_stock"
          label={t("items.fields.minStock")}
          description={t("items.fields.inBaseUnits")}
          inputMode="numeric"
          dir="ltr"
        />
        <TextField
          control={control}
          name="reorder_qty"
          label={t("items.fields.reorderQty")}
          description={t("items.fields.inBaseUnits")}
          inputMode="numeric"
          dir="ltr"
        />
      </div>
      <SwitchField control={control} name="is_controlled" label={t("items.fields.controlled")} />
    </>
  );
}
