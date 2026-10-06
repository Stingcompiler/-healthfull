import { Syringe } from "lucide-react";
import { useTranslation } from "react-i18next";

import { UnderConstruction } from "@/components/UnderConstruction";

export function NursingPage() {
  const { t } = useTranslation("nursing");
  return <UnderConstruction title={t("title")} description={t("description")} icon={<Syringe />} />;
}
