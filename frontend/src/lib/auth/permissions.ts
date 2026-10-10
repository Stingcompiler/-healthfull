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

/** Device accounts (the waiting-room kiosk, ADR 0019): held alone, never beside a person's role. */
export const DEVICE_ROLES: readonly Role[] = ["display"];

/** Roles people hold: the ones a policy (discount limits, perform-first) can name. */
export const PERSON_ROLES = ROLES.filter((r) => !DEVICE_ROLES.includes(r));

export function isDeviceRole(role: string): boolean {
  return (DEVICE_ROLES as readonly string[]).includes(role);
}

/**
 * The roles after ticking or unticking one, in `ROLES` order. A device role stands alone: ticking
 * it clears every other role, and ticking a person's role clears the device role (the server
 * refuses the mix with `DEVICE_ROLE_ALONE`).
 */
export function toggleRole(selected: readonly string[], role: Role, checked: boolean): Role[] {
  const next = new Set(selected);
  if (!checked) next.delete(role);
  else if (isDeviceRole(role)) {
    next.clear();
    next.add(role);
  } else {
    for (const device of DEVICE_ROLES) next.delete(device);
    next.add(role);
  }
  return ROLES.filter((r) => next.has(r));
}

/** Whether a set of roles mixes a device role with any other role. */
export function mixesDeviceRole(roles: readonly string[]): boolean {
  return roles.length > 1 && roles.some(isDeviceRole);
}

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
