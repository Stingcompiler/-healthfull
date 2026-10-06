import { Outlet } from "@tanstack/react-router";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";

import { Toaster } from "@/components/ui/sonner";
import { useDirection } from "@/lib/i18n-hooks";
import { usePreferences } from "@/lib/use-preferences";

export function RootLayout() {
  const { t, i18n } = useTranslation();
  const dir = useDirection();
  const { theme } = usePreferences();

  // Keep the browser tab title in the UI language.
  useEffect(() => {
    document.title = t("appName");
  }, [t, i18n.language]);

  return (
    <>
      <Outlet />
      <Toaster dir={dir} theme={theme === "dark" ? "dark" : "light"} />
    </>
  );
}
