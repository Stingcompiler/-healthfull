import { LayoutDashboard } from "lucide-react";

import type { NavItem } from "@/app/nav-types";

export const nav: NavItem[] = [
  {
    id: "dashboard",
    to: "/",
    labelKey: "dashboard",
    icon: LayoutDashboard,
    group: "overview",
    order: 0,
    exact: true,
  },
];
