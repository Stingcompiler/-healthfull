import type { MeOut } from "@/lib/api/contract";

/** Roles from ARCHITECTURE 4.10. Labels live in common:roles.<role>. */
export const ROLES = [
  "receptionist",
  "doctor",
  "cashier",
  "cashier_supervisor",
  "pharmacist",
  "lab_tech",
  "lab_supervisor",
  "nurse",
  "accountant",
  "manager",
  "admin",
  // The waiting-room kiosk account (ADR 0019): a device, not a person.
  "display",
] as const;
export type Role = (typeof ROLES)[number];

/** Roles people hold: the ones a policy (discount limits, perform-first) can name. */
export const PERSON_ROLES = ROLES.filter((r) => r !== "display");

export function isKnownRole(role: string): role is Role {
  return (ROLES as readonly string[]).includes(role);
}

/**
 * UI-only permission check (the server enforces the real rule).
 * The admin role sees everything so new modules are reachable before the
 * permission matrix grants them explicitly.
 */
export function hasPermission(
  me: Pick<MeOut, "roles" | "permissions"> | null | undefined,
  permission: string | readonly string[] | undefined,
  mode: "all" | "any" = "all",
): boolean {
  if (!me) return false;
  if (permission === undefined) return true;
  if (me.roles.includes("admin")) return true;
  const required = typeof permission === "string" ? [permission] : permission;
  if (required.length === 0) return true;
  const granted = new Set(me.permissions);
  return mode === "all" ? required.every((p) => granted.has(p)) : required.some((p) => granted.has(p));
}
