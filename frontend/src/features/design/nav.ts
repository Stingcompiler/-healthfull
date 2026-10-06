import { Palette } from "lucide-react";

import type { NavItem } from "@/app/nav-types";

/** Reachable from quick search and the user menu, not listed in the sidebar. */
export const nav: NavItem[] = [
  {
    id: "design",
    to: "/design",
    labelKey: "design",
    icon: Palette,
    group: "administration",
    order: 200,
    hidden: true,
  },
];
