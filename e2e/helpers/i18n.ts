/**
 * Reads the frontend's translation files so specs assert the exact text the
 * UI shows (and stay correct when the wording changes).
 */
import { readFileSync } from "node:fs";
import path from "node:path";

import { FRONTEND_DIR } from "../env";

export const LANGS = ["ar", "en"] as const;
export type Lang = (typeof LANGS)[number];

const cache = new Map<string, unknown>();

function namespace(lang: Lang, ns: string): unknown {
  const key = `${lang}/${ns}`;
  if (!cache.has(key)) {
    const file = path.join(FRONTEND_DIR, "src", "i18n", "locales", lang, `${ns}.json`);
    cache.set(key, JSON.parse(readFileSync(file, "utf8")) as unknown);
  }
  return cache.get(key);
}

/**
 * `tr("en", "errors:INVALID_CREDENTIALS")`, `tr("ar", "auth:login.lockedTitle")`.
 * Interpolation: `tr("en", "auth:login.lockedUntil", { time: "10:15" })`.
 */
export function tr(lang: Lang, key: string, vars: Record<string, string> = {}): string {
  const [ns, dotted] = key.includes(":") ? (key.split(":", 2) as [string, string]) : ["common", key];
  let node: unknown = namespace(lang, ns);
  for (const part of dotted.split(".")) {
    if (typeof node !== "object" || node === null || !(part in node)) {
      throw new Error(`Missing translation ${lang}:${key}`);
    }
    node = (node as Record<string, unknown>)[part];
  }
  if (typeof node !== "string") throw new Error(`Translation ${lang}:${key} is not a string`);
  return node.replace(/\{\{\s*(\w+)\s*\}\}/g, (_, name: string) => vars[name] ?? `{{${name}}}`);
}
