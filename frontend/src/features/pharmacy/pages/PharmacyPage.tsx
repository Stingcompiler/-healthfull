import { Pill } from "lucide-react";
import { useTranslation } from "react-i18next";

import { UnderConstruction } from "@/components/UnderConstruction";

export function PharmacyPage() {
  const { t } = useTranslation("pharmacy");
  return <UnderConstruction title={t("title")} description={t("description")} icon={<Pill />} />;
}
