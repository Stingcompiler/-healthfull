import { ChartColumn } from "lucide-react";

import type { NavItem } from "@/app/nav-types";

import { REPORT_PERMISSIONS } from "./catalog";

export const nav: NavItem[] = [
  {
    id: "reports",
    to: "/reports",
    labelKey: "reports",
    icon: ChartColumn,
    group: "insights",
    order: 100,
    // Any report code opens the catalog, which lists only the reports the user may open.
    permission: REPORT_PERMISSIONS,
  },
];
