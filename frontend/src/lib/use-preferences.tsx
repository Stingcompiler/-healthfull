import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import type { MeOut } from "@/lib/api/contract";
import { authKeys, meQueryOptions } from "@/lib/auth/api";
import { useUpdatePreferences } from "@/lib/auth/hooks";
import { useMediaQuery } from "@/lib/hooks/use-media-query";
import {
  applyThemeToDocument,
  cacheLanguage,
  directionOf,
  getCachedThemeSnapshot,
  isLanguage,
  DEFAULT_LANGUAGE,
  setCachedTheme,
  subscribeCachedTheme,
  type Language,
  type Theme,
} from "@/lib/preferences";

interface PreferencesValue {
  theme: Theme;
  language: Language;
  direction: "rtl" | "ltr";
  setTheme: (theme: Theme) => void;
  setLanguage: (language: Language) => void;
}

const PreferencesContext = createContext<PreferencesValue | null>(null);

/**
 * Theme and language for the whole app.
 *
 * - Logged in: the server profile (MeOut.theme/language) is the source of
 *   truth. Changes apply instantly (optimistic cache update) and are saved
 *   with PATCH /api/auth/me/preferences; on failure they stay local and a
 *   toast explains why.
 * - Logged out: the choice lives in localStorage only.
 * - No saved theme at all: follow prefers-color-scheme.
 */
export function PreferencesProvider({ children }: { children: ReactNode }) {
  const { i18n, t } = useTranslation();
  const queryClient = useQueryClient();
  const { data: me } = useQuery(meQueryOptions);
  const updatePreferences = useUpdatePreferences();

  const cachedTheme = useSyncExternalStore(subscribeCachedTheme, getCachedThemeSnapshot, () => null);
  const prefersDark = useMediaQuery("(prefers-color-scheme: dark)");
  const theme: Theme = me?.theme ?? cachedTheme ?? (prefersDark ? "dark" : "light");
  const language: Language = isLanguage(i18n.language) ? i18n.language : DEFAULT_LANGUAGE;

  // Reflect the active theme on <html data-theme>.
  useEffect(() => {
    applyThemeToDocument(theme);
  }, [theme]);

  // The server profile wins once it is known; mirror it into the local cache
  // so the next first paint (boot.js) already matches.
  const serverTheme = me?.theme;
  const serverLanguage = me?.language;
  useEffect(() => {
    if (serverTheme) setCachedTheme(serverTheme);
  }, [serverTheme]);
  useEffect(() => {
    if (serverLanguage && serverLanguage !== i18n.language) {
      void i18n.changeLanguage(serverLanguage);
    }
    if (serverLanguage) cacheLanguage(serverLanguage);
  }, [serverLanguage, i18n]);

  const persist = useCallback(
    (patch: { theme?: Theme; language?: Language }, previous: MeOut) => {
      queryClient.setQueryData<MeOut | null>(authKeys.me, { ...previous, ...patch });
      updatePreferences.mutate(patch, {
        onError: () => {
          // Keep the choice on this device; the server keeps the old value.
          queryClient.setQueryData<MeOut | null>(authKeys.me, (current) =>
            current ? { ...current, ...patch } : current,
          );
          toast.warning(t("toast.preferencesFailed"));
        },
      });
    },
    [queryClient, updatePreferences, t],
  );

  const setTheme = useCallback(
    (next: Theme) => {
      setCachedTheme(next);
      const current = queryClient.getQueryData<MeOut | null>(authKeys.me);
      if (current && current.theme !== next) persist({ theme: next }, current);
    },
    [queryClient, persist],
  );

  const setLanguage = useCallback(
    (next: Language) => {
      cacheLanguage(next);
      void i18n.changeLanguage(next);
      const current = queryClient.getQueryData<MeOut | null>(authKeys.me);
      if (current && current.language !== next) persist({ language: next }, current);
    },
    [i18n, queryClient, persist],
  );

  const value = useMemo<PreferencesValue>(
    () => ({ theme, language, direction: directionOf(language), setTheme, setLanguage }),
    [theme, language, setTheme, setLanguage],
  );

  return <PreferencesContext.Provider value={value}>{children}</PreferencesContext.Provider>;
}

export function usePreferences(): PreferencesValue {
  const value = useContext(PreferencesContext);
  if (!value) throw new Error("usePreferences must be used inside <PreferencesProvider>");
  return value;
}
