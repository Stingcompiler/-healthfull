import type { LinkProps } from "@tanstack/react-router";
import type { LucideIcon } from "lucide-react";

import type { en } from "@/i18n/resources";

/** Any absolute path the router accepts as a link target, e.g. "/patients". */
export type AppPath = Exclude<NonNullable<LinkProps["to"]>, "." | "..">;

export type NavGroup = keyof typeof en.nav.groups;
export type NavLabelKey = keyof typeof en.nav.items;

export interface NavItem {
  /** Stable id, also used as test id: nav-<id>. */
  id: string;
  to: AppPath;
  /** Key in the `nav` namespace under `items`. */
  labelKey: NavLabelKey;
  icon: LucideIcon;
  group: NavGroup;
  /** Sort order within the whole nav (lower first). */
  order: number;
  /**
   * Permission code(s); the item shows if the user has ANY of them.
   * Undefined = every logged-in user. The admin role sees everything.
   */
  permission?: string | readonly string[];
  /** Match only the exact path (for "/"). */
  exact?: boolean;
  /** Reachable from quick search but not listed in the sidebar. */
  hidden?: boolean;
  /** The icon has a reading direction (a numbered list, an arrow): mirror it in RTL. */
  flipInRtl?: boolean;
}

/** Display order of groups in the sidebar. */
export const NAV_GROUP_ORDER: readonly NavGroup[] = [
  "overview",
  "frontDesk",
  "clinical",
  "finance",
  "services",
  "insights",
  "administration",
];
