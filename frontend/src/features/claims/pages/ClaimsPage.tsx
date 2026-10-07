import { FileStack } from "lucide-react";
import { useTranslation } from "react-i18next";

import { UnderConstruction } from "@/components/UnderConstruction";

export function ClaimsPage() {
  const { t } = useTranslation("claims");
  return <UnderConstruction title={t("title")} description={t("description")} icon={<FileStack />} />;
}
