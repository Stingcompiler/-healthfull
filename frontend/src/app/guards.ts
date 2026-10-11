import { redirect, type ParsedLocation } from "@tanstack/react-router";

import type { MeOut } from "@/lib/api/contract";
import { meQueryOptions } from "@/lib/auth/api";

import type { RouterContext } from "./router-context";

interface GuardArgs {
  context: RouterContext;
  location: ParsedLocation;
}

/** Only same-app absolute paths are accepted as post-login targets. */
export function safeRedirectTarget(target: unknown): string | null {
  if (typeof target !== "string") return null;
  if (!target.startsWith("/") || target.startsWith("//") || target.startsWith("/\\")) return null;
  if (target.startsWith("/login")) return null;
  return target;
}

/** Any logged-in user; otherwise go to /login and come back afterwards. */
export async function requireUser({ context, location }: GuardArgs): Promise<MeOut> {
  const me = await context.queryClient.query({ ...meQueryOptions, staleTime: "static" });
  if (!me) {
    // eslint-disable-next-line @typescript-eslint/only-throw-error -- TanStack Router control flow
    throw redirect({ to: "/login", search: { redirect: location.href } });
  }
  return me;
}

/** Logged in and not forced to change the password first. */
export async function requireAppUser(args: GuardArgs): Promise<MeOut> {
  const me = await requireUser(args);
  if (me.must_change_password) {
    // eslint-disable-next-line @typescript-eslint/only-throw-error -- TanStack Router control flow
    throw redirect({ to: "/change-password" });
  }
  return me;
}

/** The waiting-room kiosk's only permission (ADR 0019). */
export const KIOSK_PERMISSION = "visits.view_display";

/**
 * A kiosk account (role `display`): it holds the waiting-room feed and nothing else, so every
 * staff screen sends it to `/display/queue`. A UI convenience only: the server refuses it the
 * data of every other screen.
 */
export function isKioskOnly(me: Pick<MeOut, "permissions">): boolean {
  return me.permissions.length > 0 && me.permissions.every((code) => code === KIOSK_PERMISSION);
}

/** The login page bounces a logged-in user to where they were going. */
export async function redirectIfLoggedIn({ context }: GuardArgs, target: unknown): Promise<void> {
  const me = await context.queryClient.query({ ...meQueryOptions, staleTime: "static" });
  if (!me) return;
  const href = me.must_change_password ? "/change-password" : (safeRedirectTarget(target) ?? "/");
  // eslint-disable-next-line @typescript-eslint/only-throw-error -- TanStack Router control flow
  throw redirect({ href });
}
