import { FlaskConical } from "lucide-react";
import { useTranslation } from "react-i18next";

import { UnderConstruction } from "@/components/UnderConstruction";

export function LabPage() {
  const { t } = useTranslation("lab");
  return <UnderConstruction title={t("title")} description={t("description")} icon={<FlaskConical />} />;
}
