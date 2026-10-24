import { useTranslation } from "react-i18next";

import { HELP_SHORTCUT, ShortcutsDialog as ShortcutsList } from "@/components/ShortcutsDialog";

import { RETURNS_SHORTCUT, SEARCH_SHORTCUT } from "../lib/shortcuts";

/** The documented shortcuts of the pharmacy desk (`?` opens them). `withSearch`: the screen has a scan box. */
export function ShortcutsDialog({ withSearch = false }: { withSearch?: boolean }) {
  const { t } = useTranslation("pharmacy");
  const rows = [
    ...(withSearch ? [{ combo: SEARCH_SHORTCUT, label: t("shortcuts.search") }] : []),
    { combo: RETURNS_SHORTCUT, label: t("shortcuts.returns") },
    { combo: "escape", label: t("shortcuts.close") },
    { combo: HELP_SHORTCUT, label: t("shortcuts.help") },
  ];
  return (
    <ShortcutsList
      rows={rows}
      buttonLabel={t("shortcuts.button")}
      title={t("shortcuts.title")}
      description={t("shortcuts.description")}
    />
  );
}
