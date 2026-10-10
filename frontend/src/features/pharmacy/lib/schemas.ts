import { z } from "zod";

import { vmsg } from "@/lib/validation";

import { DOSAGE_FORMS, STORAGE_CODES } from "./constants";
import { parseWhole } from "./qty";

const level = z
  .string()
  .trim()
  .refine((v) => v === "" || parseWhole(v, 0) !== null, vmsg("pharmacy:validation.wholeNumber"));

/** The editable item fields (FEATURES 8.1), shared by the new-item dialog and the item page. */
export const itemFieldsSchema = z.object({
  generic_name: z.string().trim().min(1, vmsg("validation.required")).max(200),
  brand_name: z.string().trim().max(200),
  form: z.enum(DOSAGE_FORMS),
  strength: z.string().trim().max(60),
  base_unit_name_ar: z.string().trim().min(1, vmsg("validation.required")).max(50),
  base_unit_name_en: z.string().trim().min(1, vmsg("validation.required")).max(50),
  barcode: z.string().trim().max(60),
  min_stock: level,
  reorder_qty: level,
  storage: z.enum(STORAGE_CODES),
  is_controlled: z.boolean(),
});

export type ItemFieldValues = z.infer<typeof itemFieldsSchema>;

/** A unit code: Latin letters, digits, "-" and "_" (it is the API's key for the unit). */
export const unitCodeSchema = z
  .string()
  .trim()
  .min(1, vmsg("validation.required"))
  .max(20)
  .regex(/^[a-z0-9_-]+$/i, vmsg("pharmacy:validation.unitCode"));
