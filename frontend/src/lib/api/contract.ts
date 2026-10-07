/**
 * Named aliases for the API schemas the app uses.
 *
 * Every type here comes from the generated `schema.d.ts` (`make api`: the
 * backend's `manage.py export_openapi` writes `openapi.json`, then
 * `pnpm gen:api` regenerates the types). Nothing is hand-written, so a backend
 * change shows up as a type error after `make api`, never at runtime.
 */
import type { Language, Theme } from "@/lib/preferences";

import type { components } from "./schema";

type Schemas = components["schemas"];

/** Shape of every error body returned by the API: `{code, message, details}`. */
export type ApiErrorBody = Schemas["ErrorOut"];
export type MeOut = Schemas["MeOut"];
export type LoginIn = Schemas["LoginIn"];
export type PreferencesPatch = Schemas["PreferencesPatch"];
export type ChangePasswordIn = Schemas["ChangePasswordIn"];
export type HealthOut = Schemas["HealthOut"];

/*
 * Compile-time guard: the UI's preference unions (src/lib/preferences.ts,
 * also used before login when there is no server profile) must equal the
 * backend's enums exactly. Adding a theme or language on one side only fails
 * `pnpm typecheck` here.
 */
type Assert<T extends true> = T;
type Same<A, B> = [A] extends [B] ? ([B] extends [A] ? true : false) : false;
export type ContractChecks = [
  // null = never chosen on the server (the client follows the device, ARCHITECTURE 5.1).
  Assert<Same<MeOut["language"], Language | null>>,
  Assert<Same<MeOut["theme"], Theme | null>>,
  Assert<Same<NonNullable<PreferencesPatch["language"]>, Language>>,
  Assert<Same<NonNullable<PreferencesPatch["theme"]>, Theme>>,
];
