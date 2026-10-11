import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm, type Control } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { z } from "zod";

import { Form, SelectField, TextField } from "@/components/form";
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

import { useCreateItem, useStockServices } from "../api";
import { parseWhole } from "../lib/qty";
import { itemFieldsSchema, unitCodeSchema, type ItemFieldValues } from "../lib/schemas";
import { useNames } from "../lib/use-names";
import { ErrorAlert } from "./common";
import { ItemFields } from "./ItemFields";

const schema = itemFieldsSchema.extend({
  service_id: z.string().min(1, vmsg("validation.selectOption")),
  base_unit_code: unitCodeSchema,
});

type Values = z.infer<typeof schema>;

/** Mounted only while open, so every opening starts with an empty form. */
export function NewItemDialog(props: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (id: number) => void;
}) {
  return props.open ? <NewItemDialogOpen {...props} /> : null;
}

/** A stock item for a drug or consumable service that has none yet (FEATURES 8.1). */
function NewItemDialogOpen({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (id: number) => void;
}) {
  const { t } = useTranslation(["pharmacy", "common"]);
  const translateError = useTranslateError();
  const names = useNames();
  const services = useStockServices(open);
  const create = useCreateItem();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: {
      service_id: "",
      generic_name: "",
      generic_name_ar: "",
      brand_name: "",
      form: "tablet",
      strength: "",
      base_unit_code: "tablet",
      base_unit_name_ar: "",
      base_unit_name_en: "",
      barcode: "",
      min_stock: "0",
      reorder_qty: "0",
      storage: "room",
      is_controlled: false,
    },
  });

  const submit = form.handleSubmit(async (v) => {
    setError(null);
    try {
      const item = await create.mutateAsync({
        ...v,
        service_id: Number(v.service_id),
        min_stock: parseWhole(v.min_stock, 0) ?? 0,
        reorder_qty: parseWhole(v.reorder_qty, 0) ?? 0,
      });
      onOpenChange(false);
      onCreated(item.id);
    } catch (e) {
      setError(translateError(e));
    }
  });

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!form.formState.isSubmitting) onOpenChange(next);
      }}
    >
      <DialogContent className="max-h-[92dvh] overflow-y-auto sm:max-w-2xl" data-testid="item-dialog">
        <DialogHeader>
          <DialogTitle>{t("items.newTitle")}</DialogTitle>
          <DialogDescription>{t("items.newDescription")}</DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={(e) => void submit(e)} noValidate className="grid gap-4">
            <SelectField
              control={form.control}
              name="service_id"
              label={t("items.fields.service")}
              placeholder={services.isPending ? t("common:loading") : t("items.fields.servicePlaceholder")}
              options={(services.data ?? []).map((s) => ({
                value: String(s.id),
                label: `${s.code} · ${names.name(s)}`,
              }))}
              description={services.data?.length === 0 ? t("items.fields.noServices") : undefined}
              required
            />
            <ItemFields control={form.control as unknown as Control<ItemFieldValues>} />
            <div className="grid gap-3 sm:grid-cols-3">
              <TextField
                control={form.control}
                name="base_unit_code"
                label={t("items.fields.baseUnitCode")}
                description={t("items.fields.baseUnitCodeHint")}
                dir="ltr"
                required
              />
            </div>
            <ErrorAlert message={error} />
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
              <Button type="submit" loading={form.formState.isSubmitting} data-testid="item-save">
                {t("items.create")}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
