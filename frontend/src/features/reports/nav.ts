import { ChartColumn } from "lucide-react";

import type { NavItem } from "@/app/nav-types";

export const nav: NavItem[] = [
  {
    id: "reports",
    to: "/reports",
    labelKey: "reports",
    icon: ChartColumn,
    group: "insights",
    order: 100,
    permission: "reports.view",
  },
];
