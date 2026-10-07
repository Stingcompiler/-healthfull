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
  readCachedLanguage,
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
 * Theme and language for the whole app (ARCHITECTURE 5.1).
 *
 * - Logged in with a saved choice (MeOut.theme/language not null): the server
 *   profile is the source of truth. Changes apply instantly (optimistic cache
 *   update) and are saved with PATCH /api/auth/me/preferences; on failure they
 *   stay local and a toast explains why.
 * - Logged in, never chose (null on the server): the device's choice stays (what
 *   was picked on the login page, kept in localStorage) and is saved to the
 *   profile once; with no local choice either, the theme follows
 *   prefers-color-scheme and nothing is saved, so the OS setting keeps applying.
 * - Logged out: the choice lives in localStorage only.
 *
 * The local cache only ever holds explicit choices (the user's, or a saved server
 * value): it is never filled from prefers-color-scheme, so boot.js can still
 * follow the OS for someone who never chose.
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

  // First login on a profile that never chose: save this device's explicit choices
  // (e.g. "English" picked on the login page) instead of overwriting them.
  const unsetTheme = me?.theme === null;
  const unsetLanguage = me?.language === null;
  useEffect(() => {
    if (!unsetTheme && !unsetLanguage) return;
    const current = queryClient.getQueryData<MeOut | null>(authKeys.me);
    if (!current) return;
    const patch: { theme?: Theme; language?: Language } = {};
    const localTheme = getCachedThemeSnapshot();
    const localLanguage = readCachedLanguage();
    if (current.theme === null && localTheme) patch.theme = localTheme;
    if (current.language === null && localLanguage) patch.language = localLanguage;
    if (patch.theme ?? patch.language) persist(patch, current);
  }, [unsetTheme, unsetLanguage, queryClient, persist]);

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
