import { useEffect } from "react";
import { useTranslation } from "react-i18next";

/**
 * Sets the browser tab title to "<page> - <app name>" (WCAG 2.4.2), or the app name alone
 * when `page` is empty. Called by PageHeader and by the few pages that render their own h1,
 * so every route names itself; it follows the UI language because `page` is translated.
 */
export function useDocumentTitle(page: string | undefined): void {
  const { t } = useTranslation("common");
  const appName = t("appName");
  useEffect(() => {
    document.title = page ? `${page} - ${appName}` : appName;
  }, [page, appName]);
}
