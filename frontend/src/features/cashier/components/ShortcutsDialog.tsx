import { useTranslation } from "react-i18next";

import { HELP_SHORTCUT, ShortcutsDialog as ShortcutsList } from "@/components/ShortcutsDialog";

import { INVOICE_SHORTCUT } from "./BillingPanel";
import { APPROVE_SHORTCUT } from "./InvoiceCard";
import { LOOKUP_SHORTCUT } from "./LookupPanel";
import { AMOUNT_SHORTCUT, PAY_SHORTCUT } from "./PaymentPanel";

/** F10 opens credit notes and refunds: the returns desk (Design Reference 2.2 section 9). */
export const RETURNS_SHORTCUT = "f10";

export { HELP_SHORTCUT };

/** The workspace's keyboard shortcuts (documented here and in the dialog, `?` opens it). */
export function ShortcutsDialog() {
  const { t } = useTranslation("cashier");
  const rows = [
    { combo: LOOKUP_SHORTCUT, label: t("shortcuts.lookup") },
    { combo: INVOICE_SHORTCUT, label: t("shortcuts.invoice") },
    { combo: APPROVE_SHORTCUT, label: t("shortcuts.approve") },
    { combo: AMOUNT_SHORTCUT, label: t("shortcuts.amount") },
    { combo: "alt+1", label: t("shortcuts.methods") },
    { combo: PAY_SHORTCUT, label: t("shortcuts.pay") },
    { combo: RETURNS_SHORTCUT, label: t("shortcuts.returns") },
    { combo: "escape", label: t("shortcuts.close") },
    { combo: HELP_SHORTCUT, label: t("shortcuts.help") },
  ];
  return (
    <ShortcutsList
      rows={rows}
      buttonLabel={t("shortcuts.button")}
      title={t("shortcuts.title")}
      description={t("shortcuts.description")}
    />
  );
}
