import { Keyboard } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { KbdCombo } from "@/components/Kbd";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useShortcut } from "@/lib/hooks/use-shortcut";

import { INVOICE_SHORTCUT } from "./BillingPanel";
import { APPROVE_SHORTCUT } from "./InvoiceCard";
import { LOOKUP_SHORTCUT } from "./LookupPanel";
import { AMOUNT_SHORTCUT, PAY_SHORTCUT } from "./PaymentPanel";

export const HELP_SHORTCUT = "shift+/";

const ROWS = [
  { combo: LOOKUP_SHORTCUT, key: "lookup" },
  { combo: INVOICE_SHORTCUT, key: "invoice" },
  { combo: APPROVE_SHORTCUT, key: "approve" },
  { combo: AMOUNT_SHORTCUT, key: "amount" },
  { combo: "alt+1", key: "methods" },
  { combo: PAY_SHORTCUT, key: "pay" },
  { combo: "escape", key: "close" },
  { combo: HELP_SHORTCUT, key: "help" },
] as const;

/** The workspace's keyboard shortcuts (documented here and in the dialog, `?` opens it). */
export function ShortcutsDialog() {
  const { t } = useTranslation("cashier");
  const [open, setOpen] = useState(false);
  useShortcut(HELP_SHORTCUT, () => {
    setOpen(true);
  });
  return (
    <>
      <Button
        variant="outline"
        size="sm"
        onClick={() => {
          setOpen(true);
        }}
        className="hidden md:inline-flex"
      >
        <Keyboard aria-hidden="true" />
        {t("shortcuts.button")}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("shortcuts.title")}</DialogTitle>
            <DialogDescription>{t("shortcuts.description")}</DialogDescription>
          </DialogHeader>
          <dl className="grid gap-2 text-sm">
            {ROWS.map((row) => (
              <div key={row.key} className="flex items-center justify-between gap-4">
                <dt>{t(`shortcuts.${row.key}`)}</dt>
                <dd>
                  <KbdCombo combo={row.combo} />
                </dd>
              </div>
            ))}
          </dl>
        </DialogContent>
      </Dialog>
    </>
  );
}
