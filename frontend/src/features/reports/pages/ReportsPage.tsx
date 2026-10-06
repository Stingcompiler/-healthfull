import { ChartColumn } from "lucide-react";
import { useTranslation } from "react-i18next";

import { UnderConstruction } from "@/components/UnderConstruction";

export function ReportsPage() {
  const { t } = useTranslation("reports");
  return <UnderConstruction title={t("title")} description={t("description")} icon={<ChartColumn />} />;
}
