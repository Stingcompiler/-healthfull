import { Wallet } from "lucide-react";
import { useTranslation } from "react-i18next";

import { UnderConstruction } from "@/components/UnderConstruction";

export function CashierPage() {
  const { t } = useTranslation("cashier");
  return <UnderConstruction title={t("title")} description={t("description")} icon={<Wallet />} />;
}
