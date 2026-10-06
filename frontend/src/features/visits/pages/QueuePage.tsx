import { ListOrdered } from "lucide-react";
import { useTranslation } from "react-i18next";

import { UnderConstruction } from "@/components/UnderConstruction";

export function QueuePage() {
  const { t } = useTranslation("visits");
  return <UnderConstruction title={t("queue.title")} description={t("queue.description")} icon={<ListOrdered />} />;
}
