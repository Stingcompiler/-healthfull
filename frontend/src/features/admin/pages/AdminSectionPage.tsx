import { useTranslation } from "react-i18next";

import { UnderConstruction } from "@/components/UnderConstruction";

import { ADMIN_SECTIONS, type AdminSectionId } from "../sections";

export function AdminSectionPage({ id }: { id: AdminSectionId }) {
  const { t } = useTranslation("admin");
  const section = ADMIN_SECTIONS.find((s) => s.id === id);
  const Icon = section?.icon;
  return (
    <UnderConstruction
      title={t(`sections.${id}.title`)}
      description={t(`sections.${id}.description`)}
      icon={Icon ? <Icon /> : null}
    />
  );
}
