import { FlaskConical } from "lucide-react";

import type { NavItem } from "@/app/nav-types";

export const nav: NavItem[] = [
  {
    id: "lab",
    to: "/lab",
    labelKey: "lab",
    icon: FlaskConical,
    group: "services",
    order: 80,
    permission: "lab.view_worklist",
  },
];
