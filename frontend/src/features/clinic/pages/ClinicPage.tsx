import { Stethoscope } from "lucide-react";
import { useTranslation } from "react-i18next";

import { UnderConstruction } from "@/components/UnderConstruction";

export function ClinicPage() {
  const { t } = useTranslation("clinic");
  return <UnderConstruction title={t("title")} description={t("description")} icon={<Stethoscope />} />;
}
