import { Settings2 } from "lucide-react";

import type { NavItem } from "@/app/nav-types";

import { ADMIN_PERMISSIONS } from "./sections";

export const nav: NavItem[] = [
  {
    id: "admin",
    to: "/administration",
    labelKey: "admin",
    icon: Settings2,
    group: "administration",
    order: 110,
    permission: ADMIN_PERMISSIONS,
  },
];
