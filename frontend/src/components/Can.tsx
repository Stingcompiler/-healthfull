import type { ReactNode } from "react";

import { usePermission } from "@/lib/auth/hooks";

export interface CanProps {
  /** Permission code(s), e.g. "billing.approve_invoice". */
  permission: string | readonly string[];
  /** "all" (default) requires every code; "any" requires at least one. */
  mode?: "all" | "any";
  fallback?: ReactNode;
  children: ReactNode;
}

/**
 * Hides UI the current user cannot use. Presentation only: the server
 * enforces every permission (ARCHITECTURE 4.10).
 */
export function Can({ permission, mode = "all", fallback = null, children }: CanProps) {
  return usePermission(permission, mode) ? children : fallback;
}
