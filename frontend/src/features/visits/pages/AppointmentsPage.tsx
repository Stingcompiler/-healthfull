import { CalendarDays } from "lucide-react";
import { useTranslation } from "react-i18next";

import { UnderConstruction } from "@/components/UnderConstruction";

export function AppointmentsPage() {
  const { t } = useTranslation("visits");
  return (
    <UnderConstruction
      title={t("appointments.title")}
      description={t("appointments.description")}
      icon={<CalendarDays />}
    />
  );
}
