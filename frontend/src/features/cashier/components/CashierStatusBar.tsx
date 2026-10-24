import { useTranslation } from "react-i18next";

import { PosStatusBar } from "@/components/PosStatusBar";
import { usePermission } from "@/lib/auth/hooks";

import { useCurrentShift } from "../api";

/** The cashier desk's status bar: operator, the open shift (or none), time, connection. */
export function CashierStatusBar() {
  const { t } = useTranslation();
  const canOpen = usePermission("payments.open_shift");
  const current = useCurrentShift(canOpen);
  const number = current.data?.report?.shift.number;
  const shift = !canOpen ? undefined : current.isPending ? (
    "…"
  ) : number ? (
    <bdi className="num">{number}</bdi>
  ) : (
    t("statusBar.noShift")
  );
  return <PosStatusBar shift={shift} />;
}
