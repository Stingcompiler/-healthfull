import { Outlet } from "@tanstack/react-router";

import { Toaster } from "@/components/ui/sonner";
import { useDirection } from "@/lib/i18n-hooks";
import { usePreferences } from "@/lib/use-preferences";

export function RootLayout() {
  const dir = useDirection();
  const { theme } = usePreferences();
  // The tab title is set per page (useDocumentTitle in PageHeader and the pages with an h1).

  return (
    <>
      <Outlet />
      <Toaster dir={dir} theme={theme === "dark" ? "dark" : "light"} />
    </>
  );
}
