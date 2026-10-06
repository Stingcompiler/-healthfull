/**
 * Local (per-browser) cache of UI preferences. The server profile is the
 * source of truth once logged in; this cache gives the first paint and the
 * pre-login screens their theme and language. Keys are mirrored in
 * public/boot.js.
 */
export const LANGUAGES = ["ar", "en"] as const;
export type Language = (typeof LANGUAGES)[number];

export const THEMES = ["light", "dark", "warm"] as const;
export type Theme = (typeof THEMES)[number];

export const DEFAULT_LANGUAGE: Language = "ar";

const THEME_KEY = "hs.theme";
const LANG_KEY = "hs.lang";

export function isLanguage(value: unknown): value is Language {
  return typeof value === "string" && (LANGUAGES as readonly string[]).includes(value);
}

export function isTheme(value: unknown): value is Theme {
  return typeof value === "string" && (THEMES as readonly string[]).includes(value);
}

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Storage unavailable (private mode, quota). The preference still applies
    // for this page view and is persisted on the server when logged in.
  }
}

export function readCachedLanguage(): Language | null {
  const value = read(LANG_KEY);
  return isLanguage(value) ? value : null;
}

export function readCachedTheme(): Theme | null {
  const value = read(THEME_KEY);
  return isTheme(value) ? value : null;
}

export function cacheLanguage(language: Language): void {
  write(LANG_KEY, language);
}

export function cacheTheme(theme: Theme): void {
  write(THEME_KEY, theme);
}

export function directionOf(language: Language): "rtl" | "ltr" {
  return language === "ar" ? "rtl" : "ltr";
}

/** Theme used when the user never chose one: follow the OS setting. */
export function systemTheme(): Theme {
  return typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyThemeToDocument(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
}

export function applyLanguageToDocument(language: Language): void {
  const root = document.documentElement;
  root.lang = language;
  root.dir = directionOf(language);
}

/*
 * Tiny external store for the locally chosen theme, so React re-renders when
 * the cache changes (e.g. the server profile arrives after login).
 */
let themeSnapshot: Theme | null | undefined;
const themeListeners = new Set<() => void>();

export function subscribeCachedTheme(listener: () => void): () => void {
  themeListeners.add(listener);
  return () => {
    themeListeners.delete(listener);
  };
}

export function getCachedThemeSnapshot(): Theme | null {
  themeSnapshot ??= readCachedTheme();
  return themeSnapshot;
}

export function setCachedTheme(theme: Theme): void {
  cacheTheme(theme);
  if (themeSnapshot === theme) return;
  themeSnapshot = theme;
  for (const listener of themeListeners) listener();
}
