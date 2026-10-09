import { TriangleAlert } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useLanguage } from "@/lib/i18n-hooks";
import { pickName } from "@/lib/names";

import type { AllergyChip } from "../types";

/** Active allergies, prominent (the nurse is about to inject or dress). Nothing when none. */
export function AllergyChips({ allergies }: { allergies: readonly AllergyChip[] }) {
  const { t } = useTranslation();
  const language = useLanguage();
  if (allergies.length === 0) return null;
  return (
    <div role="group" aria-label={t("patient.allergyAlert")} className="flex flex-wrap items-center gap-1.5">
      {allergies.map((a) => (
        <span
          key={a.id}
          className="inline-flex items-center gap-1 rounded-full bg-danger px-2.5 py-1 text-xs font-semibold text-danger-contrast"
        >
          <TriangleAlert className="size-3.5" aria-hidden="true" />
          <span className="sr-only">{t("patient.allergies")}: </span>
          {pickName({ ar: a.label_ar, en: a.label_en }, language)}
        </span>
      ))}
    </div>
  );
}
