import { Users } from "lucide-react";
import { useTranslation } from "react-i18next";

import { UnderConstruction } from "@/components/UnderConstruction";

export function PatientsPage() {
  const { t } = useTranslation("patients");
  return <UnderConstruction title={t("title")} description={t("description")} icon={<Users />} />;
}
